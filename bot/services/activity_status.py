"""Activity status embed + activity log broadcasts.

Completely decoupled from the notifications/opt-in flow. No DMs.

- ``ACTIVITY_STATS_CHANNEL_ID`` — hosts two edited-in-place messages:
  1. A status embed refreshed every 5 seconds with current queue/match counts.
  2. A 24h queue-join chart refreshed on every quarter-hour clock tick
     (00, 15, 30, 45 minutes past the hour, UTC).

- ``ACTIVITY_LOG_CHANNEL_ID`` — receives one terse, anonymous line for every
  ``activity_log`` WS event (queue_join, queue_leave, match_created,
  match_completed). Match IDs only; no usernames or player identities.

Both channels are optional. If either env var is unset, the corresponding
behavior is silently skipped.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import aiohttp
import discord
import structlog

from bot.components.embeds import ActivityStatusEmbed
from bot.components.queue_activity_chart import render_queue_join_chart_png
from bot.core.config import (
    ACTIVITY_LOG_CHANNEL_ID,
    ACTIVITY_STATS_CHANNEL_ID,
    BACKEND_URL,
)
from bot.core.dependencies import get_cache
from bot.helpers.activity_analytics import (
    activity_chart_title,
    fetch_queue_join_analytics,
)
from bot.helpers.embed_branding import apply_default_embed_footer
from bot.helpers.message_helpers import (
    queue_channel_send_low,
    queue_message_edit_low,
)
from common.config import ACTIVITY_CHART_BUCKET_MINUTES
from common.datetime_helpers import ensure_utc, utc_now
from common.i18n import t

logger = structlog.get_logger(__name__)

_STATUS_POLL_INTERVAL_SECONDS = 5.0
_HTTP_TIMEOUT = 5.0
_CHART_QUARTER_HOUR_MINUTES = 15
_CHART_GAME_MODE = "1v1"
_CHART_TIME_RANGE = "24h"
_CHART_IMAGE_FILENAME = "activity.png"
_CHART_BACKOFF_INITIAL_SECONDS = 2.0
_CHART_BACKOFF_MAX_SECONDS = 300.0
_CHART_BACKOFF_MULTIPLIER = 2.0


# ---------------------------------------------------------------------------
# Status embed (5-second polling loop)
# ---------------------------------------------------------------------------


async def _fetch_activity_stats() -> dict[str, Any] | None:
    try:
        timeout = aiohttp.ClientTimeout(total=_HTTP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{BACKEND_URL}/activity/stats") as resp:
                if resp.status >= 400:
                    logger.warning(
                        "[activity_status] backend returned error",
                        status=resp.status,
                    )
                    return None
                data = await resp.json()
    except TimeoutError:
        logger.warning(
            "[activity_status] backend timed out",
            timeout_seconds=_HTTP_TIMEOUT,
        )
        return None
    except aiohttp.ClientError as e:
        logger.warning("[activity_status] backend unreachable", error=str(e))
        return None
    except Exception:
        logger.exception("[activity_status] fetch failed unexpectedly")
        return None
    return dict(data)


async def _get_activity_channel(
    client: discord.Client,
) -> discord.TextChannel | None:
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
    return channel


async def _clean_activity_channel(client: discord.Client) -> None:
    """Delete every bot-authored message in the activity channel.

    Called on startup so that a fresh status + chart can be posted
    instead of trying to reconcile whatever was left from a previous
    session.
    """
    channel = await _get_activity_channel(client)
    if channel is None:
        return
    me = client.user
    if me is None:
        return

    to_delete: list[discord.Message] = []
    try:
        async for msg in channel.history(limit=100):
            if msg.author.id == me.id:
                to_delete.append(msg)
    except discord.Forbidden:
        logger.error(
            "[activity_status] missing Read Message History on activity channel",
            channel_id=ACTIVITY_STATS_CHANNEL_ID,
        )
        return
    except Exception:
        logger.exception(
            "[activity_status] channel.history failed",
            channel_id=ACTIVITY_STATS_CHANNEL_ID,
        )
        return

    for msg in to_delete:
        try:
            await msg.delete()
        except Exception:
            logger.warning(
                "[activity_status] failed to delete bot message",
                message_id=msg.id,
            )
    if to_delete:
        logger.info(
            "[activity_status] cleaned bot messages from activity channel",
            count=len(to_delete),
        )


async def _create_status_message(
    client: discord.Client,
) -> discord.Message | None:
    channel = await _get_activity_channel(client)
    if channel is None:
        return None
    embed = ActivityStatusEmbed(
        queue_1v1_count=0,
        queue_2v2_count=0,
        active_match_count_1v1=0,
        active_match_count_2v2=0,
        last_queue_join_at_1v1=None,
        last_queue_join_at_2v2=None,
        queue_joins_last_hour_1v1=0,
        queue_joins_last_hour_2v2=0,
        matches_last_hour_1v1=0,
        matches_last_hour_2v2=0,
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
    """Clean the activity channel and post fresh status + chart messages.

    Any previous bot-authored messages are deleted. The status embed is
    posted immediately; the chart is posted if the backend is reachable
    and otherwise seeded later by ``start_chart_refresher``'s backoff.
    """
    if ACTIVITY_STATS_CHANNEL_ID is None:
        return
    await _clean_activity_channel(client)
    cache = get_cache()
    cache.activity_status_message = None
    cache.activity_chart_message = None

    status = await _create_status_message(client)
    if status is not None:
        cache.activity_status_message = status

    chart = await _create_chart_message(client)
    if chart is not None:
        cache.activity_chart_message = chart


async def _refresh_status_embed_once(client: discord.Client) -> None:
    """Edit the status embed with fresh stats. Called by the polling loop."""
    cache = get_cache()
    message = cache.activity_status_message
    if message is None:
        message = await _create_status_message(client)
        if message is None:
            return
        cache.activity_status_message = message

    stats = await _fetch_activity_stats()
    if stats is None:
        return
    embed = ActivityStatusEmbed(
        queue_1v1_count=int(stats.get("queue_1v1_count", 0)),
        queue_2v2_count=int(stats.get("queue_2v2_count", 0)),
        active_match_count_1v1=int(stats.get("active_match_count_1v1", 0)),
        active_match_count_2v2=int(stats.get("active_match_count_2v2", 0)),
        last_queue_join_at_1v1=ensure_utc(stats.get("last_queue_join_at_1v1")),
        last_queue_join_at_2v2=ensure_utc(stats.get("last_queue_join_at_2v2")),
        queue_joins_last_hour_1v1=int(stats.get("queue_joins_last_hour_1v1", 0)),
        queue_joins_last_hour_2v2=int(stats.get("queue_joins_last_hour_2v2", 0)),
        matches_last_hour_1v1=int(stats.get("matches_last_hour_1v1", 0)),
        matches_last_hour_2v2=int(stats.get("matches_last_hour_2v2", 0)),
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
# 24h queue-join chart (quarter-hour refresh)
# ---------------------------------------------------------------------------


async def _build_chart_payload() -> tuple[discord.Embed, discord.File] | None:
    """Fetch analytics and render the current 24h chart. Returns ``(embed, file)``."""
    end = utc_now()
    start = end - timedelta(hours=24)
    try:
        data = await fetch_queue_join_analytics(
            _CHART_GAME_MODE,
            start,
            end,
            bucket_minutes=ACTIVITY_CHART_BUCKET_MINUTES[_CHART_TIME_RANGE],
        )
    except Exception:
        logger.exception("[activity_status] chart analytics fetch failed")
        return None
    buckets = data.get("buckets") or []
    title = activity_chart_title("enUS", _CHART_GAME_MODE, _CHART_TIME_RANGE)
    png = render_queue_join_chart_png(
        buckets,
        title=title,
        locale="enUS",
        game_mode=_CHART_GAME_MODE,
        time_range=_CHART_TIME_RANGE,
    )
    file = discord.File(png, filename=_CHART_IMAGE_FILENAME)
    embed = discord.Embed(title=title, color=discord.Color.dark_teal())
    embed.set_image(url=f"attachment://{_CHART_IMAGE_FILENAME}")
    apply_default_embed_footer(embed, locale="enUS")
    return embed, file


async def _create_chart_message(
    client: discord.Client,
) -> discord.Message | None:
    channel = await _get_activity_channel(client)
    if channel is None:
        return None
    payload = await _build_chart_payload()
    if payload is None:
        return None
    embed, file = payload
    try:
        return await queue_channel_send_low(channel, embed=embed, file=file)
    except discord.Forbidden:
        logger.error(
            "[activity_status] missing Send Messages / Attach Files on chart channel",
            channel_id=ACTIVITY_STATS_CHANNEL_ID,
        )
        return None
    except Exception:
        logger.exception(
            "[activity_status] failed to seed chart message",
            channel_id=ACTIVITY_STATS_CHANNEL_ID,
        )
        return None


async def _refresh_chart_message_once(client: discord.Client) -> bool:
    """Edit the chart message with a freshly rendered 24h chart.

    Returns ``True`` when the chart was successfully created or edited,
    ``False`` on any failure (so the caller can decide whether to retry).
    """
    cache = get_cache()
    message = cache.activity_chart_message
    if message is None:
        message = await _create_chart_message(client)
        if message is None:
            return False
        cache.activity_chart_message = message
        return True
    payload = await _build_chart_payload()
    if payload is None:
        return False
    embed, file = payload
    try:
        await queue_message_edit_low(message, embed=embed, attachments=[file])
        return True
    except discord.NotFound:
        logger.warning("[activity_status] chart message disappeared; will rediscover")
        cache.activity_chart_message = None
        return False
    except Exception:
        logger.exception("[activity_status] chart edit failed")
        return False


def _seconds_until_next_quarter_hour(now: datetime) -> float:
    floor_minute = (
        now.minute // _CHART_QUARTER_HOUR_MINUTES
    ) * _CHART_QUARTER_HOUR_MINUTES
    floor_run = now.replace(minute=floor_minute, second=0, microsecond=0)
    next_run = floor_run + timedelta(minutes=_CHART_QUARTER_HOUR_MINUTES)
    return max(1.0, (next_run - now).total_seconds())


async def start_chart_refresher(client: discord.Client) -> None:
    """Run forever, refreshing the 24h chart.

    Performs an immediate refresh on start (with exponential backoff if the
    backend is unreachable), then continues on the clock-aligned quarter-hour.
    """
    if ACTIVITY_STATS_CHANNEL_ID is None:
        logger.info(
            "[activity_status] ACTIVITY_STATS_CHANNEL_ID unset; chart refresher skipped"
        )
        return
    logger.info(
        "[activity_status] chart refresher started",
        channel_id=ACTIVITY_STATS_CHANNEL_ID,
    )

    delay = _CHART_BACKOFF_INITIAL_SECONDS
    while True:
        try:
            ok = await _refresh_chart_message_once(client)
        except Exception:
            logger.exception("[activity_status] initial chart refresh raised")
            ok = False
        if ok:
            break
        logger.warning(
            "[activity_status] initial chart refresh failed, retrying",
            delay_seconds=delay,
        )
        await asyncio.sleep(delay)
        delay = min(delay * _CHART_BACKOFF_MULTIPLIER, _CHART_BACKOFF_MAX_SECONDS)

    while True:
        await asyncio.sleep(_seconds_until_next_quarter_hour(utc_now()))
        try:
            await _refresh_chart_message_once(client)
        except Exception:
            logger.exception("[activity_status] chart refresher iteration failed")


# ---------------------------------------------------------------------------
# Activity log (per-event anonymous broadcasts)
# ---------------------------------------------------------------------------


_LOG_KEY_BY_KIND: dict[str, str] = {
    "queue_join": "activity_log.queue_join",
    "queue_leave": "activity_log.queue_leave",
    "match_created": "activity_log.match_found",
    "match_completed": "activity_log.match_completed",
}

_LOG_COLOR_BY_KIND: dict[str, discord.Color] = {
    "queue_join": discord.Color.green(),
    "queue_leave": discord.Color.red(),
    "match_created": discord.Color.blurple(),
    "match_completed": discord.Color.gold(),
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
    body = t(key, "enUS", **format_kwargs)
    embed = discord.Embed(
        description=f"<t:{ts}> (<t:{ts}:R>)\n{body}",
        color=_LOG_COLOR_BY_KIND.get(kind, discord.Color.blurple()),
    )
    apply_default_embed_footer(embed, locale="enUS")
    try:
        await queue_channel_send_low(channel, embed=embed)
    except Exception:
        logger.exception("[activity_status] log send failed", kind=kind)
