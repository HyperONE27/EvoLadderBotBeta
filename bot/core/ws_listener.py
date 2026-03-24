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
    MatchFoundView1v1,
    MatchFoundView2v2,
    MatchReportView1v1,
    MatchReportView2v2,
    _fetch_player_info,
)
from bot.components.embeds import (
    QueueJoinActivityNotifyEmbed,
    MatchAbortedEmbed,
    MatchAbortedEmbed2v2,
    MatchAbandonedEmbed,
    MatchAbandonedEmbed2v2,
    MatchConflictEmbed,
    MatchConflictEmbed2v2,
    MatchFinalizedEmbed,
    MatchFinalizedEmbed2v2,
    MatchFoundEmbed,
    MatchInfoEmbed1v1,
    MatchInfoEmbeds2v2,
    QueueSearchingEmbed,
    TalkChannelEmbed,
)
from bot.core.config import (
    BACKEND_URL,
    ENABLE_REPLAY_VALIDATION,
    MATCH_LOG_CHANNEL_ID,
    WS_RECONNECT_BACKOFF_SECONDS,
)
from bot.core.dependencies import get_cache, get_player_locale
from bot.helpers.embed_branding import apply_default_embed_footer
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
    game_mode = data.get("game_mode", "1v1")

    logger.debug(
        f"[WS] Received event: {event}", match_id=data.get("id"), game_mode=game_mode
    )

    if event == "match_found":
        if game_mode == "2v2":
            await _on_match_found_2v2(client, data)
        else:
            await _on_match_found(client, data)
    elif event == "both_confirmed":
        if game_mode == "2v2":
            await _on_all_confirmed_2v2(client, data)
        else:
            await _on_both_confirmed(client, data)
    elif event == "match_aborted":
        if game_mode == "2v2":
            await _on_match_aborted_2v2(client, data)
        else:
            await _on_match_aborted(client, data)
    elif event == "match_abandoned":
        if game_mode == "2v2":
            await _on_match_abandoned_2v2(client, data)
        else:
            await _on_match_abandoned(client, data)
    elif event == "match_completed":
        if game_mode == "2v2":
            await _on_match_completed_2v2(client, data)
        else:
            await _on_match_completed(client, data)
    elif event == "match_conflict":
        if game_mode == "2v2":
            await _on_match_conflict_2v2(client, data)
        else:
            await _on_match_conflict(client, data)
    elif event == "talk_channel_created":
        await _on_talk_channel_created(client, data)
    elif event == "leaderboard_updated":
        _on_leaderboard_updated(data)
    elif event == "queue_join_activity":
        await _on_queue_join_activity(client, data)
    else:
        logger.warning(f"[WS] Unknown event type: {event}")


async def _on_talk_channel_created(client: discord.Client, data: dict) -> None:
    """DM all matched players with a link to their newly created talk channel."""
    message_url: str = data.get("message_url", "")
    raw_uids: list = data.get("discord_uids") or []

    for uid_raw in raw_uids:
        try:
            uid = int(uid_raw)
        except (TypeError, ValueError):
            continue
        try:
            user = await client.fetch_user(uid)
            locale = get_player_locale(uid)
            await queue_user_send_low(
                user, embed=TalkChannelEmbed(message_url, locale=locale)
            )
        except Exception:
            logger.exception(f"[WS] Failed to DM user {uid} for talk_channel_created")


async def _on_queue_join_activity(client: discord.Client, data: dict) -> None:
    """Send anonymous low-priority DMs to opt-in subscribers."""

    raw_uids = data.get("notify_discord_uids") or []
    footers: dict[str, str] = data.get("footers") or {}
    payload_locales: dict[str, str] = data.get("locales") or {}
    game_mode = str(data.get("game_mode", "1v1"))

    for uid in raw_uids:
        try:
            discord_uid = int(uid)
        except (TypeError, ValueError):
            continue
        try:
            user = await client.fetch_user(discord_uid)
        except Exception:
            logger.warning(
                "[WS] queue_join_activity fetch_user failed",
                discord_uid=discord_uid,
                exc_info=True,
            )
            continue
        # Prefer locale from payload (sourced from player's DB language column);
        # seed the bot cache so future embeds for this user are also localized.
        locale = payload_locales.get(str(discord_uid)) or get_player_locale(discord_uid)
        if str(discord_uid) in payload_locales:
            get_cache().player_locales[discord_uid] = locale
        footer = footers.get(str(discord_uid), "")
        embed = QueueJoinActivityNotifyEmbed(game_mode=game_mode, locale=locale)
        if footer:
            embed.set_footer(text=footer)
            apply_default_embed_footer(embed, locale=locale)
        await queue_user_send_low(user, embed=embed)


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
                    view=MatchFoundView1v1(match_id, match_data, locale=locale),
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
            elif isinstance(result, discord.Message):
                cache.active_match_found_messages[uid] = result

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
        embed = QueueSearchingEmbed(match_found=True, locale=locale)
        try:
            await queue_message_edit_low(msg, embed=embed, view=None)
        except discord.HTTPException as e:
            if e.status == 401:
                ch = msg.channel
                if not isinstance(ch, discord.DMChannel):
                    raise
                partial = ch.get_partial_message(msg.id)
                await queue_message_edit_low(partial, embed=embed, view=None)
            else:
                raise
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
                    embed=MatchInfoEmbed1v1(
                        match_data, p1_info, p2_info, locale=locale
                    ),
                    view=MatchReportView1v1(
                        match_id,
                        p1_name,
                        p2_name,
                        match_data,
                        p1_info,
                        p2_info,
                        report_locked=ENABLE_REPLAY_VALIDATION,
                        locale=locale,
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

    # The match-found messages already have view=None (both players pressed Confirm).
    for uid in (p1_uid, p2_uid):
        if uid is not None:
            cache.active_match_found_messages.pop(uid, None)


async def _on_match_aborted(client: discord.Client, match_data: dict) -> None:
    """Notify both players that the match was explicitly aborted by a player."""
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    p1_info = await _fetch_player_info(p1_uid) if p1_uid else None
    p2_info = await _fetch_player_info(p2_uid) if p2_uid else None

    await _clear_match_found_messages_low(p1_uid, p2_uid)
    await _send_to_both_localized(
        client, p1_uid, p2_uid, MatchAbortedEmbed, match_data, p1_info, p2_info
    )
    await _clear_match_state_low(p1_uid, p2_uid)
    await _post_to_match_log_low(
        client, MatchAbortedEmbed(match_data, p1_info, p2_info, locale="enUS")
    )


async def _on_match_abandoned(client: discord.Client, match_data: dict) -> None:
    """Notify both players that the match was abandoned (confirmation timeout)."""
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    p1_info = await _fetch_player_info(p1_uid) if p1_uid else None
    p2_info = await _fetch_player_info(p2_uid) if p2_uid else None

    await _clear_match_found_messages_low(p1_uid, p2_uid)
    await _send_to_both_localized(
        client, p1_uid, p2_uid, MatchAbandonedEmbed, match_data, p1_info, p2_info
    )
    await _clear_match_state_low(p1_uid, p2_uid)
    await _post_to_match_log_low(
        client, MatchAbandonedEmbed(match_data, p1_info, p2_info, locale="enUS")
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
        client, MatchFinalizedEmbed(match_data, p1_info, p2_info, locale="enUS")
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
        client, MatchConflictEmbed(match_data, p1_info, p2_info, locale="enUS")
    )


async def _on_match_found_2v2(client: discord.Client, match_data: dict) -> None:
    """Send match found DMs to team leaders only and update searching embeds for all 4."""
    match_id: int = match_data["id"]
    all_uids = _get_2v2_uids(match_data)
    leader_uids = _get_2v2_leader_uids(match_data)
    cache = get_cache()

    dm_coros = []
    dm_uids: list[int] = []
    for uid in leader_uids:
        try:
            user = await client.fetch_user(uid)
            locale = get_player_locale(uid)
            dm_coros.append(
                queue_user_send_high(
                    user,
                    embed=MatchFoundEmbed(match_data, locale=locale),
                    view=MatchFoundView2v2(match_id, locale=locale),
                )
            )
            dm_uids.append(uid)
        except Exception:
            logger.exception(f"[WS] Failed to fetch user {uid} for 2v2 match_found")

    if dm_coros:
        results = await asyncio.gather(*dm_coros, return_exceptions=True)
        for uid, result in zip(dm_uids, results):
            if isinstance(result, Exception):
                logger.exception(
                    f"[WS] Failed to DM user {uid} for 2v2 match_found", exc_info=result
                )
            elif isinstance(result, discord.Message):
                cache.active_match_found_messages[uid] = result

    for uid in all_uids:
        searching_view = cache.active_searching_views.pop(uid, None)
        if searching_view is not None and hasattr(searching_view, "stop_heartbeat"):
            searching_view.stop_heartbeat()
        searching_msg = cache.active_searching_messages.pop(uid, None)
        if searching_msg is not None:
            asyncio.create_task(_edit_searching_embed_low(searching_msg, uid))


async def _on_all_confirmed_2v2(client: discord.Client, match_data: dict) -> None:
    """Send match info DMs to all 4 players with the report dropdown."""
    match_id: int = match_data["id"]
    all_uids = _get_2v2_uids(match_data)
    cache = get_cache()

    # Fetch player infos for all 4 players concurrently.
    info_results = await asyncio.gather(
        *(_fetch_player_info(uid) for uid in all_uids), return_exceptions=True
    )
    infos: dict[int, dict | None] = {}
    for uid, result in zip(all_uids, info_results):
        infos[uid] = result if isinstance(result, dict) else None

    dm_coros = []
    dm_uids: list[int] = []
    for uid in all_uids:
        cache.active_match_info[uid] = {"match_data": match_data, "player_infos": infos}
        try:
            user = await client.fetch_user(uid)
            locale = get_player_locale(uid)
            dm_coros.append(
                queue_user_send_high(
                    user,
                    embeds=MatchInfoEmbeds2v2(match_data, infos, locale=locale),
                    view=MatchReportView2v2(match_id, match_data, infos, locale=locale),
                )
            )
            dm_uids.append(uid)
        except Exception:
            logger.exception(f"[WS] Failed to fetch user {uid} for 2v2 all_confirmed")

    if dm_coros:
        dm_results = await asyncio.gather(*dm_coros, return_exceptions=True)
        for uid, dm_result in zip(dm_uids, dm_results):
            if isinstance(dm_result, Exception):
                logger.exception(
                    f"[WS] Failed to DM user {uid} for 2v2 all_confirmed",
                    exc_info=dm_result,
                )
            elif isinstance(dm_result, discord.Message):
                cache.active_match_messages[uid] = dm_result

    for uid in all_uids:
        cache.active_match_found_messages.pop(uid, None)


async def _on_match_aborted_2v2(client: discord.Client, match_data: dict) -> None:
    all_uids = _get_2v2_uids(match_data)
    player_infos = await _fetch_player_infos_2v2(all_uids)
    await _send_to_all_2v2_localized(
        client, all_uids, MatchAbortedEmbed2v2, match_data, player_infos
    )
    await _clear_match_state_all_2v2(all_uids)
    await _post_to_match_log_low(
        client,
        MatchAbortedEmbed2v2(match_data, player_infos=player_infos, locale="enUS"),
    )


async def _on_match_abandoned_2v2(client: discord.Client, match_data: dict) -> None:
    all_uids = _get_2v2_uids(match_data)
    player_infos = await _fetch_player_infos_2v2(all_uids)
    await _send_to_all_2v2_localized(
        client, all_uids, MatchAbandonedEmbed2v2, match_data, player_infos
    )
    await _clear_match_state_all_2v2(all_uids)
    await _post_to_match_log_low(
        client,
        MatchAbandonedEmbed2v2(match_data, player_infos=player_infos, locale="enUS"),
    )


async def _on_match_completed_2v2(client: discord.Client, match_data: dict) -> None:
    all_uids = _get_2v2_uids(match_data)
    player_infos = await _fetch_player_infos_2v2(all_uids)
    await _send_to_all_2v2_localized(
        client, all_uids, MatchFinalizedEmbed2v2, match_data, player_infos
    )
    await _clear_match_state_all_2v2(all_uids)
    await _post_to_match_log_low(
        client,
        MatchFinalizedEmbed2v2(match_data, player_infos=player_infos, locale="enUS"),
    )


async def _on_match_conflict_2v2(client: discord.Client, match_data: dict) -> None:
    all_uids = _get_2v2_uids(match_data)
    player_infos = await _fetch_player_infos_2v2(all_uids)
    await _send_to_all_2v2_localized(
        client, all_uids, MatchConflictEmbed2v2, match_data, player_infos
    )
    await _clear_match_state_all_2v2(all_uids)
    await _post_to_match_log_low(
        client,
        MatchConflictEmbed2v2(match_data, player_infos=player_infos, locale="enUS"),
    )


def _on_leaderboard_updated(data: dict) -> None:
    """Replace the cached leaderboard with the new data from the backend."""
    cache = get_cache()
    entries_1v1 = data.get("leaderboard", [])
    entries_2v2 = data.get("leaderboard_2v2", [])
    cache.leaderboard_1v1 = entries_1v1
    cache.leaderboard_2v2 = entries_2v2
    logger.info(
        f"[WS] Leaderboard cache updated: {len(entries_1v1)} 1v1, {len(entries_2v2)} 2v2 entries"
    )


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


async def _clear_match_found_messages_low(
    p1_uid: int | None, p2_uid: int | None
) -> None:
    """Remove confirm/abort buttons from match-found messages (for the non-acting player)."""
    cache = get_cache()
    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue
        match_found_msg = cache.active_match_found_messages.pop(uid, None)
        if match_found_msg is not None:
            try:
                await queue_message_edit_low(match_found_msg, view=None)
            except Exception:
                logger.exception(
                    f"[WS] Failed to remove buttons from match_found message for user {uid}"
                )


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


def _get_2v2_uids(match_data: dict) -> list[int]:
    """Return all 4 player UIDs from a 2v2 match data dict (non-None only)."""
    uids: list[int] = []
    for key in (
        "team_1_player_1_discord_uid",
        "team_1_player_2_discord_uid",
        "team_2_player_1_discord_uid",
        "team_2_player_2_discord_uid",
    ):
        uid = match_data.get(key)
        if uid is not None:
            uids.append(int(uid))
    return uids


def _get_2v2_leader_uids(match_data: dict) -> list[int]:
    """Return the 2 team leader UIDs (player_1 of each team)."""
    uids: list[int] = []
    for key in ("team_1_player_1_discord_uid", "team_2_player_1_discord_uid"):
        uid = match_data.get(key)
        if uid is not None:
            uids.append(int(uid))
    return uids


def _get_cached_player_infos_2v2(
    uids: list[int],
) -> dict[int, dict[str, object] | None]:
    """Retrieve player_infos from the active_match_info cache (set during both_confirmed)."""
    cache = get_cache()
    for uid in uids:
        match_info = cache.active_match_info.get(uid)
        if match_info is not None:
            infos: dict[int, dict[str, object] | None] = match_info.get(
                "player_infos", {}
            )
            return infos
    return {}


async def _fetch_player_infos_2v2(
    uids: list[int],
) -> dict[int, dict | None]:
    """Fetch fresh player nationality info for all 2v2 players via HTTP."""
    results = await asyncio.gather(
        *(_fetch_player_info(uid) for uid in uids), return_exceptions=True
    )
    return {uid: (r if isinstance(r, dict) else None) for uid, r in zip(uids, results)}


async def _send_to_all_2v2_localized(
    client: discord.Client,
    uids: list[int],
    embed_cls: type,
    match_data: dict,
    player_infos: dict[int, dict | None] | None = None,
) -> None:
    """DM all players with per-locale embeds."""
    for uid in uids:
        try:
            locale = get_player_locale(uid)
            user = await client.fetch_user(uid)
            await queue_user_send_low(
                user,
                embed=embed_cls(match_data, player_infos=player_infos, locale=locale),
            )
        except Exception:
            logger.exception(f"[WS] Failed to DM 2v2 user {uid}")


async def _clear_match_state_all_2v2(uids: list[int]) -> None:
    """Clear all match state for a 2v2 match: remove found-message buttons and disable report views."""
    cache = get_cache()
    for uid in uids:
        found_msg = cache.active_match_found_messages.pop(uid, None)
        if found_msg is not None:
            try:
                await queue_message_edit_low(found_msg, view=None)
            except Exception:
                logger.exception(
                    f"[WS] Failed to remove buttons from 2v2 match_found message for user {uid}"
                )
        match_msg = cache.active_match_messages.pop(uid, None)
        if match_msg is not None:
            try:
                await queue_message_edit_low(match_msg, view=None)
            except Exception:
                logger.exception(
                    f"[WS] Failed to disable 2v2 MatchReportView for user {uid}"
                )
        cache.active_match_info.pop(uid, None)
