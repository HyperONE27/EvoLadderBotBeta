"""
WebSocket listener that connects to the backend and dispatches real-time events
(match_found, both_confirmed, match_aborted, match_abandoned, match_completed,
match_conflict) to the appropriate Discord users via DM.

Event semantics:
  match_aborted   — a player explicitly pressed Abort Match
  match_abandoned — the confirmation window expired (no response from one/both players)
"""

import asyncio
import json

import aiohttp
import discord
import structlog

from bot.components.views import (
    MatchFoundView,
    MatchReportView,
    _fetch_player_info,
)
from bot.components.embeds import (
    MatchAbortedEmbed,
    MatchAbandonedEmbed,
    MatchConflictEmbed,
    MatchFinalizedEmbed,
    MatchFoundEmbed,
    MatchInfoEmbed,
    QueueSearchingEmbed,
)
from bot.core.config import (
    BACKEND_URL,
    ENABLE_REPLAY_VALIDATION,
    MATCH_LOG_CHANNEL_ID,
    WS_RECONNECT_BACKOFF_SECONDS,
)
from bot.core.dependencies import get_cache, get_player_locale
from bot.helpers.message_helpers import (
    queue_channel_send_low,
    queue_message_edit_low,
    queue_user_send_high,
    queue_user_send_low,
)

logger = structlog.get_logger(__name__)


async def start_ws_listener(client: discord.Client) -> None:
    """Connect to the backend WebSocket and handle events forever.

    Reconnects automatically on disconnect.
    """
    ws_url = BACKEND_URL.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = ws_url.rstrip("/") + "/ws"

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(ws_url) as ws:
                    logger.info(f"[WS] Connected to backend at {ws_url}")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await _handle_message(client, msg.data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error("[WS] WebSocket error", error=ws.exception())
                            break
        except Exception:
            logger.exception("[WS] Connection failed, reconnecting in 5s")

        await asyncio.sleep(WS_RECONNECT_BACKOFF_SECONDS)


async def _handle_message(client: discord.Client, raw: str) -> None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("[WS] Received invalid JSON", raw=raw)
        return

    event = payload.get("event")
    data = payload.get("data", {})

    logger.debug(f"[WS] Received event: {event}", match_id=data.get("id"))

    if event == "match_found":
        await _on_match_found(client, data)
    elif event == "both_confirmed":
        await _on_both_confirmed(client, data)
    elif event == "match_aborted":
        await _on_match_aborted(client, data)
    elif event == "match_abandoned":
        await _on_match_abandoned(client, data)
    elif event == "match_completed":
        await _on_match_completed(client, data)
    elif event == "match_conflict":
        await _on_match_conflict(client, data)
    elif event == "leaderboard_updated":
        _on_leaderboard_updated(data)
    else:
        logger.warning(f"[WS] Unknown event type: {event}")


async def _on_match_found(client: discord.Client, match_data: dict) -> None:
    """Send match found DMs to both players and update their searching embeds."""
    match_id: int = match_data["id"]
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")
    cache = get_cache()

    # --- High priority: DM both players with confirm/abort buttons ---
    dm_coros = []
    dm_uids: list[int] = []
    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue
        try:
            user = await client.fetch_user(uid)
            locale = get_player_locale(uid)
            dm_coros.append(
                queue_user_send_high(
                    user,
                    embed=MatchFoundEmbed(match_data, locale=locale),
                    view=MatchFoundView(match_id, match_data, locale=locale),
                )
            )
            dm_uids.append(uid)
        except Exception:
            logger.exception(f"[WS] Failed to fetch user {uid} for match_found")

    # Send all DMs concurrently (high priority — worker drains these first).
    if dm_coros:
        results = await asyncio.gather(*dm_coros, return_exceptions=True)
        for uid, result in zip(dm_uids, results):
            if isinstance(result, Exception):
                logger.exception(
                    f"[WS] Failed to DM user {uid} for match_found", exc_info=result
                )

    # --- Low priority: update searching embeds (fire-and-forget) ---
    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue

        searching_view = cache.active_searching_views.pop(uid, None)
        if searching_view is not None and hasattr(searching_view, "stop_heartbeat"):
            searching_view.stop_heartbeat()

        searching_msg = cache.active_searching_messages.pop(uid, None)
        if searching_msg is not None:
            asyncio.create_task(
                _edit_searching_embed_low(searching_msg, uid),
            )


async def _edit_searching_embed_low(msg: discord.Message, uid: int) -> None:
    """Fire-and-forget low-priority edit of a searching embed."""
    try:
        locale = get_player_locale(uid)
        await queue_message_edit_low(
            msg, embed=QueueSearchingEmbed(match_found=True, locale=locale), view=None
        )
    except Exception:
        logger.exception(f"[WS] Failed to update searching embed for user {uid}")


async def _on_both_confirmed(client: discord.Client, match_data: dict) -> None:
    """Send a new message with match details + report dropdown to both players."""
    match_id: int = match_data["id"]
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")
    p1_name = match_data.get("player_1_name", "Player 1")
    p2_name = match_data.get("player_2_name", "Player 2")
    cache = get_cache()

    p1_info = await _fetch_player_info(p1_uid) if p1_uid else None
    p2_info = await _fetch_player_info(p2_uid) if p2_uid else None
    # _fetch_player_info seeds player_locales as a side effect.

    # High priority: DM both players with per-locale MatchInfoEmbed concurrently.
    dm_coros = []
    dm_uids: list[int] = []
    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue

        cache.active_match_info[uid] = {
            "match_data": match_data,
            "p1_info": p1_info,
            "p2_info": p2_info,
        }

        try:
            user = await client.fetch_user(uid)
            locale = get_player_locale(uid)
            dm_coros.append(
                queue_user_send_high(
                    user,
                    embed=MatchInfoEmbed(match_data, p1_info, p2_info, locale=locale),
                    view=MatchReportView(
                        match_id,
                        p1_name,
                        p2_name,
                        match_data,
                        p1_info,
                        p2_info,
                        report_locked=ENABLE_REPLAY_VALIDATION,
                    ),
                )
            )
            dm_uids.append(uid)
        except Exception:
            logger.exception(f"[WS] Failed to fetch user {uid} for both_confirmed")

    if dm_coros:
        results = await asyncio.gather(*dm_coros, return_exceptions=True)
        for uid, result in zip(dm_uids, results):
            if isinstance(result, Exception):
                logger.exception(
                    f"[WS] Failed to DM user {uid} for both_confirmed",
                    exc_info=result,
                )
            elif isinstance(result, discord.Message):
                cache.active_match_messages[uid] = result


async def _on_match_aborted(client: discord.Client, match_data: dict) -> None:
    """Notify both players that the match was explicitly aborted by a player."""
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    p1_info = await _fetch_player_info(p1_uid) if p1_uid else None
    p2_info = await _fetch_player_info(p2_uid) if p2_uid else None

    await _send_to_both_localized(
        client, p1_uid, p2_uid, MatchAbortedEmbed, match_data, p1_info, p2_info
    )
    await _clear_match_state_low(p1_uid, p2_uid)
    await _post_to_match_log_low(
        client, MatchAbortedEmbed(match_data, p1_info, p2_info)
    )


async def _on_match_abandoned(client: discord.Client, match_data: dict) -> None:
    """Notify both players that the match was abandoned (confirmation timeout)."""
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    p1_info = await _fetch_player_info(p1_uid) if p1_uid else None
    p2_info = await _fetch_player_info(p2_uid) if p2_uid else None

    await _send_to_both_localized(
        client, p1_uid, p2_uid, MatchAbandonedEmbed, match_data, p1_info, p2_info
    )
    await _clear_match_state_low(p1_uid, p2_uid)
    await _post_to_match_log_low(
        client, MatchAbandonedEmbed(match_data, p1_info, p2_info)
    )


async def _on_match_completed(client: discord.Client, match_data: dict) -> None:
    """Notify both players of the completed match and post to match log."""
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    p1_info = await _fetch_player_info(p1_uid) if p1_uid else None
    p2_info = await _fetch_player_info(p2_uid) if p2_uid else None

    await _send_to_both_localized(
        client, p1_uid, p2_uid, MatchFinalizedEmbed, match_data, p1_info, p2_info
    )
    await _clear_match_state_low(p1_uid, p2_uid)
    await _post_to_match_log_low(
        client, MatchFinalizedEmbed(match_data, p1_info, p2_info)
    )


async def _on_match_conflict(client: discord.Client, match_data: dict) -> None:
    """Notify both players of the conflicting reports and post to match log."""
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    p1_info = await _fetch_player_info(p1_uid) if p1_uid else None
    p2_info = await _fetch_player_info(p2_uid) if p2_uid else None

    await _send_to_both_localized(
        client, p1_uid, p2_uid, MatchConflictEmbed, match_data, p1_info, p2_info
    )
    await _clear_match_state_low(p1_uid, p2_uid)
    await _post_to_match_log_low(
        client, MatchConflictEmbed(match_data, p1_info, p2_info)
    )


def _on_leaderboard_updated(data: dict) -> None:
    """Replace the cached leaderboard with the new data from the backend."""
    cache = get_cache()
    entries = data.get("leaderboard", [])
    cache.leaderboard_1v1 = entries
    logger.info(f"[WS] Leaderboard cache updated: {len(entries)} entries")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _send_to_both_localized(
    client: discord.Client,
    p1_uid: int | None,
    p2_uid: int | None,
    embed_cls: type,
    *args: object,
) -> None:
    """DM both players with per-locale embeds built from embed_cls(*args, locale=...)."""
    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue
        try:
            locale = get_player_locale(uid)
            user = await client.fetch_user(uid)
            await queue_user_send_low(user, embed=embed_cls(*args, locale=locale))
        except Exception:
            logger.exception(f"[WS] Failed to DM user {uid}")


async def _clear_match_state_low(p1_uid: int | None, p2_uid: int | None) -> None:
    """
    Remove match tracking from the cache and disable the MatchReportView
    on each player's MatchInfoEmbed message so stale dropdowns can't be used.
    """
    cache = get_cache()
    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue

        match_msg = cache.active_match_messages.pop(uid, None)
        if match_msg is not None:
            try:
                await queue_message_edit_low(match_msg, view=None)
            except Exception:
                logger.exception(
                    f"[WS] Failed to disable MatchReportView for user {uid}"
                )

        cache.active_match_info.pop(uid, None)


async def _post_to_match_log_low(
    client: discord.Client,
    embed: discord.Embed,
) -> None:
    """Post a pre-built embed to the configured match log channel."""
    try:
        channel = client.get_channel(MATCH_LOG_CHANNEL_ID)
        if channel is None:
            channel = await client.fetch_channel(MATCH_LOG_CHANNEL_ID)
        if channel is None or not isinstance(channel, discord.TextChannel):
            logger.warning("[WS] Match log channel not found or not a text channel")
            return
        await queue_channel_send_low(channel, embed=embed)
    except Exception:
        logger.exception("[WS] Failed to post to match log channel")
