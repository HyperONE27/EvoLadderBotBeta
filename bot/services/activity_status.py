"""Single in-place-edited activity-status embed + anonymous broadcasts.

Two separate Discord channels (set via env):

- ``ACTIVITY_STATS_CHANNEL_ID`` — hosts the one edited-in-place status embed.
  Startup scans for a previous message authored by us and reuses it, otherwise
  posts a fresh one. Edits throttle to ≤1 per ``_STATS_EDIT_MIN_INTERVAL`` s.

- ``ACTIVITY_LOG_CHANNEL_ID`` — hosts anonymous join/leave/match-found/
  match-completed broadcasts. Terse by design; no player identities.

Both channels are optional. If either env var is unset, the corresponding
behavior is silently skipped.
"""

from __future__ import annotations

import asyncio
import structlog
from typing import Any

import aiohttp
import discord

from bot.components.embeds import ActivityStatusEmbed
from bot.core.config import (
    ACTIVITY_LOG_CHANNEL_ID,
    ACTIVITY_STATS_CHANNEL_ID,
    BACKEND_URL,
)
from bot.core.dependencies import get_cache
from bot.helpers.message_helpers import (
    queue_channel_send_low,
    queue_message_edit_low,
)
from common.datetime_helpers import ensure_utc
from common.i18n import t

logger = structlog.get_logger(__name__)

_STATS_EDIT_MIN_INTERVAL = 5.0  # seconds, per-message rate-limit margin
_HTTP_TIMEOUT = 5.0

_last_edit_monotonic: float = 0.0
_edit_lock = asyncio.Lock()


async def _fetch_activity_stats() -> dict[str, Any] | None:
    """Fetch current stats from the backend. Returns None on failure."""
    try:
        timeout = aiohttp.ClientTimeout(total=_HTTP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{BACKEND_URL}/activity/stats") as resp:
                if resp.status >= 400:
                    return None
                data = await resp.json()
    except Exception:
        logger.exception("[activity_status] fetch failed")
        return None
    return dict(data)


async def _discover_or_create_status_message(
    client: discord.Client,
) -> discord.Message | None:
    if ACTIVITY_STATS_CHANNEL_ID is None:
        return None
    channel = client.get_channel(
        ACTIVITY_STATS_CHANNEL_ID
    ) or await client.fetch_channel(ACTIVITY_STATS_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        logger.error(
            "[activity_status] channel is not a TextChannel",
            channel_id=ACTIVITY_STATS_CHANNEL_ID,
        )
        return None
    me = client.user
    if me is None:
        return None
    async for msg in channel.history(limit=50):
        if msg.author.id == me.id and msg.embeds:
            return msg
    # No prior message — post a fresh placeholder embed.
    embed = ActivityStatusEmbed(
        queue_1v1_count=0,
        queue_2v2_count=0,
        active_match_count=0,
        last_queue_join_at=None,
        last_hour_match_count=0,
    )
    return await queue_channel_send_low(channel, embed=embed)


async def on_ready(client: discord.Client) -> None:
    """Discover or create the single status message. Idempotent under reconnect."""
    cache = get_cache()
    if cache.activity_status_message is not None:
        return
    message = await _discover_or_create_status_message(client)
    if message is not None:
        cache.activity_status_message = message
        await refresh_status_embed()


async def refresh_status_embed() -> None:
    """Edit the status embed with fresh stats. Throttled to 1 per 5s."""
    cache = get_cache()
    message = cache.activity_status_message
    if message is None:
        return

    async with _edit_lock:
        loop = asyncio.get_running_loop()
        global _last_edit_monotonic
        elapsed = loop.time() - _last_edit_monotonic
        if elapsed < _STATS_EDIT_MIN_INTERVAL:
            await asyncio.sleep(_STATS_EDIT_MIN_INTERVAL - elapsed)

        stats = await _fetch_activity_stats()
        if stats is None:
            return
        last_join = ensure_utc(stats.get("last_queue_join_at"))
        embed = ActivityStatusEmbed(
            queue_1v1_count=int(stats.get("queue_1v1_count", 0)),
            queue_2v2_count=int(stats.get("queue_2v2_count", 0)),
            active_match_count=int(stats.get("active_match_count", 0)),
            last_queue_join_at=last_join,
            last_hour_match_count=int(stats.get("last_hour_match_count", 0)),
        )
        try:
            await queue_message_edit_low(message, embed=embed)
        except discord.NotFound:
            logger.warning("[activity_status] message disappeared; will rediscover")
            cache.activity_status_message = None
            return
        except Exception:
            logger.exception("[activity_status] edit failed")
            return
        _last_edit_monotonic = loop.time()


async def broadcast_queue_join(client: discord.Client, game_mode: str) -> None:
    await _broadcast(client, "activity_log.queue_join", game_mode=game_mode)


async def broadcast_queue_leave(
    client: discord.Client, game_mode: str, duration_minutes: int | None = None
) -> None:
    if duration_minutes is not None:
        await _broadcast(
            client,
            "activity_log.queue_leave_with_duration",
            game_mode=game_mode,
            minutes=str(duration_minutes),
        )
    else:
        await _broadcast(client, "activity_log.queue_leave", game_mode=game_mode)


async def broadcast_match_found(
    client: discord.Client, match_id: int, game_mode: str
) -> None:
    await _broadcast(
        client,
        "activity_log.match_found",
        game_mode=game_mode,
        match_id=str(match_id),
    )


async def broadcast_match_completed(
    client: discord.Client, match_id: int, game_mode: str
) -> None:
    await _broadcast(
        client,
        "activity_log.match_completed",
        game_mode=game_mode,
        match_id=str(match_id),
    )


async def _broadcast(client: discord.Client, key: str, **kwargs: str) -> None:
    if ACTIVITY_LOG_CHANNEL_ID is None:
        return
    try:
        channel = client.get_channel(
            ACTIVITY_LOG_CHANNEL_ID
        ) or await client.fetch_channel(ACTIVITY_LOG_CHANNEL_ID)
    except Exception:
        logger.exception(
            "[activity_status] broadcast fetch_channel failed",
            channel_id=ACTIVITY_LOG_CHANNEL_ID,
        )
        return
    if not isinstance(channel, discord.TextChannel):
        return
    content = t(key, "enUS", **kwargs)
    try:
        await queue_channel_send_low(channel, content=content)
    except Exception:
        logger.exception("[activity_status] broadcast send failed", key=key)
