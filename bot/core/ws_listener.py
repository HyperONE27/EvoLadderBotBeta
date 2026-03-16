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
    MatchCompletedEmbed,
    MatchConfirmedEmbed,
    MatchFoundEmbed,
    MatchFoundView,
    MatchReportView,
    _fetch_player_info,
)
from bot.core.config import BACKEND_URL, MATCH_LOG_CHANNEL_ID

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
    """Send match found DMs to both players with confirm/abort buttons."""
    match_id: int = match_data["id"]
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue
        try:
            user = await client.fetch_user(uid)
            await user.send(
                embed=MatchFoundEmbed(match_data),
                view=MatchFoundView(match_id, match_data),
            )
        except Exception:
            logger.exception(f"[WS] Failed to DM user {uid} for match_found")


async def _on_both_confirmed(client: discord.Client, match_data: dict) -> None:
    """Send a NEW message with match details + report dropdown to both players."""
    match_id: int = match_data["id"]
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")
    p1_name = match_data.get("player_1_name", "Player 1")
    p2_name = match_data.get("player_2_name", "Player 2")

    p1_info = await _fetch_player_info(p1_uid) if p1_uid else None
    p2_info = await _fetch_player_info(p2_uid) if p2_uid else None
    embed = MatchConfirmedEmbed(match_data, p1_info, p2_info)

    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue
        try:
            user = await client.fetch_user(uid)
            await user.send(
                embed=embed,
                view=MatchReportView(match_id, p1_name, p2_name),
            )
        except Exception:
            logger.exception(f"[WS] Failed to DM user {uid} for both_confirmed")

    await _post_to_match_log(client, match_id, match_data, "Match Started")


async def _on_match_aborted(client: discord.Client, match_data: dict) -> None:
    """Notify both players that the match was explicitly aborted by a player."""
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue
        try:
            user = await client.fetch_user(uid)
            await user.send(embed=MatchAbortedEmbed(match_data=match_data))
        except Exception:
            logger.exception(f"[WS] Failed to DM user {uid} for match_aborted")

    await _post_to_match_log(client, match_data.get("id"), match_data, "Match Aborted")


async def _on_match_abandoned(client: discord.Client, match_data: dict) -> None:
    """Notify both players that the match was abandoned (confirmation timeout)."""
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue
        try:
            user = await client.fetch_user(uid)
            await user.send(embed=MatchAbortedEmbed(match_data=match_data))
        except Exception:
            logger.exception(f"[WS] Failed to DM user {uid} for match_abandoned")

    await _post_to_match_log(
        client, match_data.get("id"), match_data, "Match Abandoned"
    )


async def _on_match_completed(client: discord.Client, match_data: dict) -> None:
    """Notify both players of the completed match and post to match log."""
    match_id: int = match_data["id"]
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue
        try:
            user = await client.fetch_user(uid)
            await user.send(embed=MatchCompletedEmbed(match_data))
        except Exception:
            logger.exception(f"[WS] Failed to DM user {uid} for match_completed")

    await _post_to_match_log(client, match_id, match_data, "Match Completed")


async def _on_match_conflict(client: discord.Client, match_data: dict) -> None:
    """Notify both players of the conflicting reports and post to match log."""
    match_id: int = match_data["id"]
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue
        try:
            user = await client.fetch_user(uid)
            await user.send(embed=MatchCompletedEmbed(match_data))
        except Exception:
            logger.exception(f"[WS] Failed to DM user {uid} for match_conflict")

    await _post_to_match_log(
        client, match_id, match_data, "Match Conflict (Invalidated)"
    )


async def _post_to_match_log(
    client: discord.Client,
    match_id: int | None,
    match_data: dict,
    title: str,
) -> None:
    """Post a match summary to the configured match log channel."""
    try:
        channel = client.get_channel(MATCH_LOG_CHANNEL_ID)
        if channel is None:
            channel = await client.fetch_channel(MATCH_LOG_CHANNEL_ID)
        if channel is None or not isinstance(channel, discord.TextChannel):
            logger.warning("[WS] Match log channel not found or not a text channel")
            return

        p1_name = match_data.get("player_1_name", "?")
        p2_name = match_data.get("player_2_name", "?")
        map_name = match_data.get("map_name", "?")

        embed = discord.Embed(
            title=title,
            description=(
                f"**Match #{match_id}**\n{p1_name} vs {p2_name}\nMap: {map_name}"
            ),
            color=discord.Color.blue(),
        )

        result = match_data.get("match_result")
        if result:
            embed.add_field(name="Result", value=result, inline=True)

        p1_change = match_data.get("player_1_mmr_change")
        p2_change = match_data.get("player_2_mmr_change")
        if p1_change is not None and p2_change is not None:
            sign1 = "+" if p1_change >= 0 else ""
            sign2 = "+" if p2_change >= 0 else ""
            embed.add_field(
                name="MMR Changes",
                value=f"{p1_name}: {sign1}{p1_change}\n{p2_name}: {sign2}{p2_change}",
                inline=True,
            )

        await channel.send(embed=embed)
    except Exception:
        logger.exception("[WS] Failed to post to match log channel")
