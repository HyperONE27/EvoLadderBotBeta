"""Deferred ``queue_join_activity`` DMs with a commitment delay + cooldown sweep.

We want to avoid pinging subscribers when the queuer immediately bails. We hold
each wave of DMs for ``QUEUE_NOTIFY_COMMITMENT_SECONDS`` and let the match-found
/ queue-leave handlers cancel the pending task if the joiner bails during that
window. Subscriber cooldowns already live on the backend; this module is purely
in-memory and is lost on bot restart.

The ``joiner_discord_uid`` field must be present on the ``queue_join_activity``
WS payload for cancellation to work. Payloads without it still fire, they just
can't be cancelled early.
"""

from __future__ import annotations

import asyncio
import structlog
from typing import Callable, Coroutine, Any

import discord

logger = structlog.get_logger(__name__)

_DeferredSend = Callable[[discord.Client, dict[str, Any]], Coroutine[Any, Any, None]]

# joiner_discord_uid -> pending task
_deferred_tasks: dict[int, asyncio.Task[None]] = {}


def schedule_deferred_ping(
    client: discord.Client,
    data: dict[str, Any],
    *,
    commitment_seconds: int,
    send: _DeferredSend,
) -> None:
    """Hold the DM wave for ``commitment_seconds``, then send.

    The backend only emits ``queue_join_activity`` for a joiner who is
    currently in the queue (initial broadcast) or still in the queue
    (sweep re-broadcast), so we trust the payload. If the joiner bails
    during the commitment window the match-found / queue-leave handlers
    will call ``cancel_deferred_ping`` to drop the pending task.

    If a pending task already exists for this joiner, we keep it: the backend
    re-fires ``queue_join_activity`` from the sweep loop every
    ``QUEUE_NOTIFY_SWEEP_INTERVAL_SECONDS``, and if we reset the timer on every
    sweep tick the DM would never get to fire.
    """
    raw = data.get("joiner_discord_uid")
    try:
        joiner_uid = int(raw) if raw is not None else None
    except TypeError, ValueError:
        joiner_uid = None

    if joiner_uid is None:
        asyncio.create_task(send(client, data))
        return

    existing = _deferred_tasks.get(joiner_uid)
    if existing is not None and not existing.done():
        return

    async def _runner() -> None:
        try:
            await asyncio.sleep(commitment_seconds)
            await send(client, data)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "[activity_notifier] deferred ping failed",
                joiner_discord_uid=joiner_uid,
            )
        finally:
            _deferred_tasks.pop(joiner_uid, None)

    _deferred_tasks[joiner_uid] = asyncio.create_task(
        _runner(), name=f"activity-notifier-{joiner_uid}"
    )


def cancel_deferred_ping(joiner_discord_uid: int) -> None:
    """Cancel a pending wave for this joiner, if any."""
    task = _deferred_tasks.pop(joiner_discord_uid, None)
    if task is not None and not task.done():
        task.cancel()
