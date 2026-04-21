"""Activity status embed + activity log broadcasts.

Completely decoupled from the notifications/opt-in flow. No DMs.

- ``ACTIVITY_STATS_CHANNEL_ID`` — hosts a single edited-in-place embed that
  displays the current queue state. Refreshed every 5 seconds by an
  independent polling task, regardless of whether any WS events fire.

- ``ACTIVITY_LOG_CHANNEL_ID`` — receives one terse, anonymous line for every
  ``activity_log`` WS event (queue_join, queue_leave, match_created,
  match_completed). Match IDs only; no usernames or player identities.

Both channels are optional. If either env var is unset, the corresponding
behavior is silently skipped.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import discord
import structlog

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
from common.datetime_helpers import ensure_utc, utc_now
from common.i18n import t

logger = structlog.get_logger(__name__)

_STATUS_POLL_INTERVAL_SECONDS = 5.0
_HTTP_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# Status embed (5-second polling loop)
# ---------------------------------------------------------------------------


async def _fetch_activity_stats() -> dict[str, Any] | None:
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
    try:
        channel = client.get_channel(
            ACTIVITY_STATS_CHANNEL_ID
        ) or await client.fetch_channel(ACTIVITY_STATS_CHANNEL_ID)
    except Exception:
        logger.exception(
            "[activity_status] fetch_channel failed",
            channel_id=ACTIVITY_STATS_CHANNEL_ID,
        )
        return None
    if not isinstance(channel, discord.TextChannel):
        logger.error(
            "[activity_status] channel is not a TextChannel",
            channel_id=ACTIVITY_STATS_CHANNEL_ID,
            channel_type=type(channel).__name__,
        )
        return None
    me = client.user
    if me is None:
        return None
    try:
        async for msg in channel.history(limit=50):
            if msg.author.id == me.id and msg.embeds:
                return msg
    except discord.Forbidden:
        logger.error(
            "[activity_status] missing Read Message History on status channel",
            channel_id=ACTIVITY_STATS_CHANNEL_ID,
        )
        return None
    except Exception:
        logger.exception(
            "[activity_status] channel.history failed",
            channel_id=ACTIVITY_STATS_CHANNEL_ID,
        )
        return None
    embed = ActivityStatusEmbed(
        queue_1v1_count=0,
        queue_2v2_count=0,
        active_match_count=0,
        last_queue_join_at=None,
        last_hour_match_count=0,
    )
    try:
        return await queue_channel_send_low(channel, embed=embed)
    except discord.Forbidden:
        logger.error(
            "[activity_status] missing Send Messages on status channel",
            channel_id=ACTIVITY_STATS_CHANNEL_ID,
        )
        return None
    except Exception:
        logger.exception(
            "[activity_status] failed to seed status embed",
            channel_id=ACTIVITY_STATS_CHANNEL_ID,
        )
        return None


async def on_ready(client: discord.Client) -> None:
    """Discover or create the single status message. Idempotent under reconnect."""
    if ACTIVITY_STATS_CHANNEL_ID is None:
        return
    cache = get_cache()
    if cache.activity_status_message is not None:
        return
    message = await _discover_or_create_status_message(client)
    if message is not None:
        cache.activity_status_message = message


async def _refresh_status_embed_once(client: discord.Client) -> None:
    """Edit the status embed with fresh stats. Called by the polling loop."""
    cache = get_cache()
    message = cache.activity_status_message
    if message is None:
        message = await _discover_or_create_status_message(client)
        if message is None:
            return
        cache.activity_status_message = message

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
    except Exception:
        logger.exception("[activity_status] edit failed")


async def start_status_poller(client: discord.Client) -> None:
    """Run forever, refreshing the status embed on a fixed 5s cadence."""
    if ACTIVITY_STATS_CHANNEL_ID is None:
        logger.info(
            "[activity_status] ACTIVITY_STATS_CHANNEL_ID unset; status poller skipped"
        )
        return
    logger.info(
        "[activity_status] status poller started",
        channel_id=ACTIVITY_STATS_CHANNEL_ID,
        interval_seconds=_STATUS_POLL_INTERVAL_SECONDS,
    )
    while True:
        try:
            await _refresh_status_embed_once(client)
        except Exception:
            logger.exception("[activity_status] poller iteration failed")
        await asyncio.sleep(_STATUS_POLL_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# Activity log (per-event anonymous broadcasts)
# ---------------------------------------------------------------------------


_LOG_KEY_BY_KIND: dict[str, str] = {
    "queue_join": "activity_log.queue_join",
    "queue_leave": "activity_log.queue_leave",
    "match_created": "activity_log.match_found",
    "match_completed": "activity_log.match_completed",
}

_FLAVOR_SUFFIX = {"bw", "sc2", "both"}


def _format_duration(wait_seconds: int) -> str:
    """Human-readable duration with hours/minutes dropped when zero.

    Examples: ``45 seconds``, ``2 minutes, 5 seconds``,
    ``1 hour, 0 minutes, 3 seconds``.
    """
    wait_seconds = max(0, int(wait_seconds))
    hours, remainder = divmod(wait_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    def _unit(value: int, singular: str) -> str:
        return f"{value} {singular}" if value == 1 else f"{value} {singular}s"

    if hours > 0:
        return f"{_unit(hours, 'hour')}, {_unit(minutes, 'minute')}, {_unit(seconds, 'second')}"
    if minutes > 0:
        return f"{_unit(minutes, 'minute')}, {_unit(seconds, 'second')}"
    return _unit(seconds, "second")


async def on_activity_log(client: discord.Client, data: dict[str, Any]) -> None:
    """Post one anonymous line to the activity-log channel for a single event."""
    if ACTIVITY_LOG_CHANNEL_ID is None:
        return
    kind = str(data.get("kind") or "")
    key = _LOG_KEY_BY_KIND.get(kind)
    if key is None:
        logger.warning("[activity_status] unknown activity_log kind", kind=kind)
        return
    game_mode = str(data.get("game_mode") or "1v1")
    format_kwargs: dict[str, str] = {"game_mode": game_mode}
    match_id = data.get("match_id")
    if match_id is not None:
        format_kwargs["match_id"] = str(match_id)

    if kind == "queue_join":
        flavor = data.get("flavor")
        if isinstance(flavor, str) and flavor in _FLAVOR_SUFFIX:
            key = f"{key}.{flavor}"
    elif kind == "queue_leave":
        wait_seconds = data.get("wait_seconds")
        if isinstance(wait_seconds, (int, float)):
            format_kwargs["duration"] = _format_duration(int(wait_seconds))
            key = "activity_log.queue_leave_with_duration"

    try:
        channel = client.get_channel(
            ACTIVITY_LOG_CHANNEL_ID
        ) or await client.fetch_channel(ACTIVITY_LOG_CHANNEL_ID)
    except Exception:
        logger.exception(
            "[activity_status] log fetch_channel failed",
            channel_id=ACTIVITY_LOG_CHANNEL_ID,
        )
        return
    if not isinstance(channel, discord.TextChannel):
        return

    ts = int(utc_now().timestamp())
    content = f"<t:{ts}> (<t:{ts}:R>) {t(key, 'enUS', **format_kwargs)}"
    try:
        await queue_channel_send_low(channel, content=content)
    except Exception:
        logger.exception("[activity_status] log send failed", kind=kind)
