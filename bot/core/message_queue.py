"""
Prioritized message queue for non-interaction Discord API calls.

Interaction endpoints (response, followup, edit_original_response) are NOT
rate-limited by Discord's global gateway limit and must NOT be routed through
this queue.  Only direct REST calls (user.send, channel.send, message.edit,
message.delete, message.reply) go here.

Architecture:
- High-priority queue: Player-facing sends where the player is actively waiting
  (match-found DMs, MatchInfoEmbed DMs, replay detail embeds, processing acks).
- Low-priority queue: Everything else (terminal-event DMs, match-log posts,
  view-disabling edits, admin-resolve DMs, searching-embed edits).
- Single worker task that always drains the high-priority queue before touching
  low-priority jobs.
- Rate limiting: 40 messages/second (configurable via DISCORD_MESSAGE_RATE_LIMIT).
  Guarantees at most 1 send per rolling 1/40th-second window.
- Retry strategy: Re-queue to back on failure (max 3 attempts).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

import discord
import structlog

from bot.core.config import DISCORD_MESSAGE_RATE_LIMIT

logger = structlog.get_logger(__name__)


@dataclass
class MessageQueueJob:
    """A job representing a Discord API call to be executed.

    Attributes:
        operation:   Zero-argument async callable that returns a fresh coroutine
                     on each invocation (NOT a coroutine object — must be
                     callable to support retries).
        future:      asyncio.Future for result propagation.  The same Future
                     instance is reused across all retry attempts.
        retry_count: Number of retry attempts already made (max 3).
        job_type:    "high" or "low" for logging purposes.
    """

    operation: Callable[[], Awaitable[object]]
    future: asyncio.Future[object]
    retry_count: int = 0
    job_type: str = "unknown"


class MessageQueue:
    """Two-tier priority queue for non-interaction Discord API calls.

    Manages two queues with strict priority ordering:
    - High-priority queue: Always processed first.
    - Low-priority queue: Only processed when high-priority queue is empty.
    """

    def __init__(self) -> None:
        self._high_priority_queue: asyncio.Queue[MessageQueueJob] = asyncio.Queue()
        self._low_priority_queue: asyncio.Queue[MessageQueueJob] = asyncio.Queue()

        self._worker_task: asyncio.Task[None] | None = None
        self._running: bool = False

        self._rate_limit: float = float(DISCORD_MESSAGE_RATE_LIMIT)
        self._min_interval: float = 1.0 / self._rate_limit
        self._next_allowed_time: float = time.monotonic()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("message_queue.started", rate_limit=self._rate_limit)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._worker_task:
            await self._worker_task
        remaining_high = self._high_priority_queue.qsize()
        remaining_low = self._low_priority_queue.qsize()
        if remaining_high or remaining_low:
            logger.warning(
                "message_queue.shutdown_pending",
                high=remaining_high,
                low=remaining_low,
            )

    # ------------------------------------------------------------------
    # Public enqueue methods
    # ------------------------------------------------------------------

    async def enqueue_high(
        self, operation: Callable[[], Awaitable[object]]
    ) -> asyncio.Future[object]:
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        job = MessageQueueJob(operation=operation, future=future, job_type="high")
        await self._high_priority_queue.put(job)
        return future

    async def enqueue_low(
        self, operation: Callable[[], Awaitable[object]]
    ) -> asyncio.Future[object]:
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        job = MessageQueueJob(operation=operation, future=future, job_type="low")
        await self._low_priority_queue.put(job)
        return future

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    async def _worker_loop(self) -> None:
        while self._running:
            try:
                # Always drain high-priority queue first.
                while not self._high_priority_queue.empty():
                    job = await self._high_priority_queue.get()
                    await self._execute_job(job, "high")

                # Process one low-priority job, then re-check high-priority.
                if not self._low_priority_queue.empty():
                    job = await self._low_priority_queue.get()
                    await self._execute_job(job, "low")
                else:
                    await asyncio.sleep(0.01)
            except Exception:
                logger.exception("message_queue.worker_error")
                await asyncio.sleep(0.1)

    # ------------------------------------------------------------------
    # Rate limiter
    # ------------------------------------------------------------------

    async def _enforce_rate_limit(self) -> None:
        now = time.monotonic()
        if now < self._next_allowed_time:
            await asyncio.sleep(self._next_allowed_time - now)
        self._next_allowed_time = max(
            self._next_allowed_time + self._min_interval,
            time.monotonic(),
        )

    # ------------------------------------------------------------------
    # Job execution
    # ------------------------------------------------------------------

    async def _execute_job(self, job: MessageQueueJob, queue_type: str) -> None:
        await self._enforce_rate_limit()

        try:
            result = await job.operation()
            if not job.future.done():
                job.future.set_result(result)

        except AttributeError as exc:
            # discord.py internal state issue — message was likely sent.
            if "is_finished" in str(exc):
                logger.warning(
                    "message_queue.discord_internal_error",
                    job_type=job.job_type,
                    error=str(exc),
                )
                if not job.future.done():
                    job.future.set_result(None)
            else:
                self._handle_failure(job, queue_type, exc)

        except discord.NotFound as exc:
            if exc.code == 10008:  # Unknown Message — already deleted
                if not job.future.done():
                    job.future.set_result(None)
            else:
                self._handle_failure(job, queue_type, exc)

        except Exception as exc:
            self._handle_failure(job, queue_type, exc)

    def _handle_failure(
        self, job: MessageQueueJob, queue_type: str, exc: Exception
    ) -> None:
        if job.retry_count < 3:
            job.retry_count += 1
            logger.warning(
                "message_queue.retry",
                job_type=job.job_type,
                attempt=job.retry_count,
                error=str(exc),
            )
            target = (
                self._high_priority_queue
                if queue_type == "high"
                else self._low_priority_queue
            )
            target.put_nowait(job)
        else:
            logger.error(
                "message_queue.max_retries",
                job_type=job.job_type,
                error=str(exc),
            )
            if not job.future.done():
                job.future.set_exception(exc)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_queue_stats(self) -> dict[str, object]:
        return {
            "high_count": self._high_priority_queue.qsize(),
            "low_count": self._low_priority_queue.qsize(),
            "running": self._running,
            "rate_limit": self._rate_limit,
        }


# ======================================================================
# Global singleton
# ======================================================================

_message_queue: MessageQueue | None = None


def initialize_message_queue() -> MessageQueue:
    global _message_queue
    _message_queue = MessageQueue()
    return _message_queue


def get_message_queue() -> MessageQueue:
    if _message_queue is None:
        raise RuntimeError(
            "MessageQueue not initialized — call initialize_message_queue() first"
        )
    return _message_queue
