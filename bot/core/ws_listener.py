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

from bot.commands.user.queue_command import (
    MatchAbortedEmbed,
    MatchAbandonedEmbed,
    MatchFinalizedEmbed,
    MatchConflictEmbed,
    MatchInfoEmbed,
    MatchFoundEmbed,
    MatchFoundView,
    MatchReportView,
    QueueSearchingEmbed,
    _ENABLE_REPLAY_VALIDATION,
    _fetch_player_info,
)
from bot.core.config import BACKEND_URL, MATCH_LOG_CHANNEL_ID
from bot.core.dependencies import get_cache

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

        await asyncio.sleep(5)


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
    else:
        logger.warning(f"[WS] Unknown event type: {event}")


async def _on_match_found(client: discord.Client, match_data: dict) -> None:
    """Send match found DMs to both players and update their searching embeds."""
    match_id: int = match_data["id"]
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")
    cache = get_cache()

    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue

        # Send the match-found DM with confirm/abort buttons.
        try:
            user = await client.fetch_user(uid)
            await user.send(
                embed=MatchFoundEmbed(match_data),
                view=MatchFoundView(match_id, match_data),
            )
        except Exception:
            logger.exception(f"[WS] Failed to DM user {uid} for match_found")

        # Edit the QueueSearchingEmbed: stop timer, remove cancel button, add
        # "match found" field.
        searching_msg = cache.active_searching_messages.pop(uid, None)
        if searching_msg is not None:
            try:
                await searching_msg.edit(
                    embed=QueueSearchingEmbed(match_found=True),
                    view=None,
                )
            except Exception:
                logger.exception(
                    f"[WS] Failed to update searching embed for user {uid}"
                )


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
    embed = MatchInfoEmbed(match_data, p1_info, p2_info)

    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue

        # Store match context so the replay handler can act on DM uploads.
        cache.active_match_info[uid] = {
            "match_data": match_data,
            "p1_info": p1_info,
            "p2_info": p2_info,
        }

        try:
            user = await client.fetch_user(uid)
            msg = await user.send(
                embed=embed,
                view=MatchReportView(
                    match_id,
                    p1_name,
                    p2_name,
                    match_data,
                    p1_info,
                    p2_info,
                    report_locked=_ENABLE_REPLAY_VALIDATION,
                ),
            )
            # Keep a reference so the replay handler can edit it later.
            cache.active_match_messages[uid] = msg
        except Exception:
            logger.exception(f"[WS] Failed to DM user {uid} for both_confirmed")


async def _on_match_aborted(client: discord.Client, match_data: dict) -> None:
    """Notify both players that the match was explicitly aborted by a player."""
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    p1_info = await _fetch_player_info(p1_uid) if p1_uid else None
    p2_info = await _fetch_player_info(p2_uid) if p2_uid else None
    embed = MatchAbortedEmbed(match_data, p1_info, p2_info)

    await _send_to_both(client, p1_uid, p2_uid, embed)
    await _clear_match_state(p1_uid, p2_uid)
    await _post_to_match_log(client, embed)


async def _on_match_abandoned(client: discord.Client, match_data: dict) -> None:
    """Notify both players that the match was abandoned (confirmation timeout)."""
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    p1_info = await _fetch_player_info(p1_uid) if p1_uid else None
    p2_info = await _fetch_player_info(p2_uid) if p2_uid else None
    embed = MatchAbandonedEmbed(match_data, p1_info, p2_info)

    await _send_to_both(client, p1_uid, p2_uid, embed)
    await _clear_match_state(p1_uid, p2_uid)
    await _post_to_match_log(client, embed)


async def _on_match_completed(client: discord.Client, match_data: dict) -> None:
    """Notify both players of the completed match and post to match log."""
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    p1_info = await _fetch_player_info(p1_uid) if p1_uid else None
    p2_info = await _fetch_player_info(p2_uid) if p2_uid else None
    embed = MatchFinalizedEmbed(match_data, p1_info, p2_info)

    await _send_to_both(client, p1_uid, p2_uid, embed)
    await _clear_match_state(p1_uid, p2_uid)
    await _post_to_match_log(client, embed)


async def _on_match_conflict(client: discord.Client, match_data: dict) -> None:
    """Notify both players of the conflicting reports and post to match log."""
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    p1_info = await _fetch_player_info(p1_uid) if p1_uid else None
    p2_info = await _fetch_player_info(p2_uid) if p2_uid else None
    embed = MatchConflictEmbed(match_data, p1_info, p2_info)

    await _send_to_both(client, p1_uid, p2_uid, embed)
    await _clear_match_state(p1_uid, p2_uid)
    await _post_to_match_log(client, embed)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _send_to_both(
    client: discord.Client,
    p1_uid: int | None,
    p2_uid: int | None,
    embed: discord.Embed,
) -> None:
    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue
        try:
            user = await client.fetch_user(uid)
            await user.send(embed=embed)
        except Exception:
            logger.exception(f"[WS] Failed to DM user {uid}")


async def _clear_match_state(p1_uid: int | None, p2_uid: int | None) -> None:
    """
    Remove match tracking from the cache and disable the MatchReportView
    on each player's MatchInfoEmbed message so stale dropdowns can't be used.
    """
    cache = get_cache()
    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue

        # Disable the report dropdown on the match info message.
        match_msg = cache.active_match_messages.pop(uid, None)
        if match_msg is not None:
            try:
                await match_msg.edit(view=None)
            except Exception:
                logger.exception(
                    f"[WS] Failed to disable MatchReportView for user {uid}"
                )

        cache.active_match_info.pop(uid, None)


async def _post_to_match_log(
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
        await channel.send(embed=embed)
    except Exception:
        logger.exception("[WS] Failed to post to match log channel")
