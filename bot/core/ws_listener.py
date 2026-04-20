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
    MatchAbortedMinimalEmbed,
    MatchAbandonedMinimalEmbed,
    MatchConflictEmbed,
    MatchConflictEmbed2v2,
    MatchFinalizedEmbed,
    MatchFinalizedEmbed2v2,
    MatchFoundEmbed,
    LobbyGuideEmbed,
    MatchInfoEmbed1v1,
    MatchInfoEmbeds2v2,
    Party2v2QueueCancelledEmbed,
    Party2v2QueueStartedEmbed,
    QueueSearchingEmbed,
    TalkChannelEmbed,
)
from bot.core.config import (
    BACKEND_URL,
    ENABLE_REPLAY_VALIDATION,
    MATCH_LOG_CHANNEL_ID,
    QUEUE_NOTIFY_COMMITMENT_SECONDS,
    WS_RECONNECT_BACKOFF_SECONDS,
)
from bot.services import activity_status
from bot.services.activity_notifier import (
    cancel_deferred_ping,
    schedule_deferred_ping,
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
                            asyncio.create_task(
                                _handle_message(client, msg.data),
                                name=f"ws-event-{msg.data[:50]}",
                            )
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

    logger.info(
        "[WS] Event received",
        ws_event=event,
        match_id=data.get("id"),
        game_mode=game_mode,
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
    elif event == "queue_started":
        await _on_queue_started_2v2(client, data)
    elif event == "queue_cancelled":
        await _on_queue_cancelled_2v2(client, data)
    else:
        logger.warning(f"[WS] Unknown event type: {event}")


async def _on_talk_channel_created(client: discord.Client, data: dict) -> None:
    """DM all matched players with a link to their newly created talk channel."""
    message_url: str = data.get("message_url", "")
    raw_uids: list = data.get("discord_uids") or []

    for uid_raw in raw_uids:
        try:
            uid = int(uid_raw)
        except TypeError, ValueError:
            continue
        try:
            user = await client.fetch_user(uid)
            locale = get_player_locale(uid)
            await queue_user_send_low(
                user, embed=TalkChannelEmbed(message_url, locale=locale)
            )
        except Exception:
            logger.exception(f"[WS] Failed to DM user {uid} for talk_channel_created")


def _joiner_still_queued(joiner_uid: int) -> bool:
    """True if the joiner is still in our local queue-tracking caches."""
    cache = get_cache()
    if joiner_uid in cache.active_match_info:
        return False
    return joiner_uid in cache.active_searching_messages


async def _on_queue_join_activity(client: discord.Client, data: dict) -> None:
    """Schedule anonymous low-priority DMs after the commitment delay."""
    game_mode = str(data.get("game_mode", "1v1"))
    asyncio.create_task(activity_status.broadcast_queue_join(client, game_mode))
    asyncio.create_task(activity_status.refresh_status_embed())
    schedule_deferred_ping(
        client,
        data,
        commitment_seconds=QUEUE_NOTIFY_COMMITMENT_SECONDS,
        still_queued=_joiner_still_queued,
        send=_dispatch_queue_join_activity,
    )


async def _dispatch_queue_join_activity(client: discord.Client, data: dict) -> None:
    """Send anonymous low-priority DMs to opt-in subscribers."""

    raw_uids = data.get("notify_discord_uids") or []
    footers: dict[str, str] = data.get("footers") or {}
    payload_locales: dict[str, str] = data.get("locales") or {}
    game_mode = str(data.get("game_mode", "1v1"))
    queue_type: str | None = data.get("queue_type")

    unreachable: list[int] = []
    for uid in raw_uids:
        try:
            discord_uid = int(uid)
        except TypeError, ValueError:
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
        embed = QueueJoinActivityNotifyEmbed(
            game_mode=game_mode, queue_type=queue_type, locale=locale
        )
        if footer:
            embed.set_footer(text=footer)
            apply_default_embed_footer(embed, locale=locale)
        try:
            await queue_user_send_low(user, embed=embed)
        except discord.Forbidden:
            unreachable.append(discord_uid)
        except Exception:
            logger.warning(
                "[WS] queue_join_activity DM failed",
                discord_uid=discord_uid,
                exc_info=True,
            )
    if unreachable:
        logger.info(
            "[WS] queue_join_activity unreachable subscribers",
            count=len(unreachable),
            discord_uids=unreachable,
            game_mode=game_mode,
        )


async def _on_queue_started_2v2(client: discord.Client, data: dict) -> None:
    """DM the 2v2 party partner that their leader has started a queue search."""
    asyncio.create_task(activity_status.refresh_status_embed())
    partner_raw = data.get("partner_discord_uid")
    try:
        partner_uid = int(partner_raw) if partner_raw is not None else None
    except TypeError, ValueError:
        partner_uid = None
    if partner_uid is None:
        logger.warning("[WS] queue_started missing partner_discord_uid", data=data)
        return

    races: dict = data.get("races") or {}
    map_vetoes: list[str] = list(data.get("map_vetoes") or [])

    try:
        user = await client.fetch_user(partner_uid)
    except Exception:
        logger.exception(
            "[WS] queue_started fetch_user failed", partner_uid=partner_uid
        )
        return

    locale = get_player_locale(partner_uid)
    embed = Party2v2QueueStartedEmbed(
        pure_bw_leader_race=races.get("pure_bw_leader_race"),
        pure_bw_member_race=races.get("pure_bw_member_race"),
        mixed_leader_race=races.get("mixed_leader_race"),
        mixed_member_race=races.get("mixed_member_race"),
        pure_sc2_leader_race=races.get("pure_sc2_leader_race"),
        pure_sc2_member_race=races.get("pure_sc2_member_race"),
        map_vetoes=map_vetoes,
        locale=locale,
    )
    try:
        await queue_user_send_low(user, embed=embed)
    except Exception:
        logger.exception("[WS] queue_started DM failed", partner_uid=partner_uid)


async def _on_queue_cancelled_2v2(client: discord.Client, data: dict) -> None:
    """DM the 2v2 party partner that their leader has left the queue."""
    asyncio.create_task(activity_status.refresh_status_embed())
    partner_raw = data.get("partner_discord_uid")
    try:
        partner_uid = int(partner_raw) if partner_raw is not None else None
    except TypeError, ValueError:
        partner_uid = None
    if partner_uid is None:
        logger.warning("[WS] queue_cancelled missing partner_discord_uid", data=data)
        return

    try:
        user = await client.fetch_user(partner_uid)
    except Exception:
        logger.exception(
            "[WS] queue_cancelled fetch_user failed", partner_uid=partner_uid
        )
        return

    locale = get_player_locale(partner_uid)
    try:
        await queue_user_send_low(
            user, embed=Party2v2QueueCancelledEmbed(locale=locale)
        )
    except Exception:
        logger.exception("[WS] queue_cancelled DM failed", partner_uid=partner_uid)


async def _on_match_found(client: discord.Client, match_data: dict) -> None:
    """Send match found DMs to both players and update their searching embeds."""
    match_id: int = match_data["id"]
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")
    for uid in (p1_uid, p2_uid):
        if uid is not None:
            cancel_deferred_ping(int(uid))
    asyncio.create_task(activity_status.broadcast_match_found(client, match_id, "1v1"))
    asyncio.create_task(activity_status.refresh_status_embed())
    cache = get_cache()
    logger.info(
        "[WS] match_found handler start",
        match_id=match_id,
        p1_uid=p1_uid,
        p2_uid=p2_uid,
    )

    # --- High priority: DM both players with confirm/abort buttons ---
    dm_coros = []
    dm_uids: list[int] = []
    dm_views: list[MatchFoundView1v1] = []
    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue
        try:
            user = await client.fetch_user(uid)
            logger.info("[WS] fetch_user OK", match_id=match_id, uid=uid)
            locale = get_player_locale(uid)
            view = MatchFoundView1v1(match_id, match_data, locale=locale)
            dm_coros.append(
                queue_user_send_high(
                    user,
                    embed=MatchFoundEmbed(match_data, locale=locale),
                    view=view,
                )
            )
            dm_uids.append(uid)
            dm_views.append(view)
        except Exception:
            logger.exception(
                "[WS] fetch_user FAILED for match_found",
                match_id=match_id,
                uid=uid,
            )

    # Send all DMs concurrently (high priority — worker drains these first).
    if dm_coros:
        results = await asyncio.gather(*dm_coros, return_exceptions=True)
        for uid, view, result in zip(dm_uids, dm_views, results):
            if isinstance(result, Exception):
                logger.error(
                    "[WS] DM delivery FAILED for match_found",
                    match_id=match_id,
                    uid=uid,
                    error=str(result),
                )
            elif isinstance(result, discord.Message):
                view.message = result
                cache.active_match_found_messages[uid] = result
                logger.info(
                    "[WS] DM delivered for match_found",
                    match_id=match_id,
                    uid=uid,
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
    logger.info(
        "[WS] both_confirmed handler start",
        match_id=match_id,
        p1_uid=p1_uid,
        p2_uid=p2_uid,
    )

    # Fetch player info concurrently (seeds player_locales as a side effect).
    uids_to_fetch = [uid for uid in (p1_uid, p2_uid) if uid is not None]
    info_results = await asyncio.gather(
        *(_fetch_player_info(uid) for uid in uids_to_fetch),
        return_exceptions=True,
    )
    info_map: dict[int, dict | None] = {}
    for uid, info_result in zip(uids_to_fetch, info_results):
        info_map[uid] = info_result if isinstance(info_result, dict) else None

    p1_info = info_map.get(p1_uid) if p1_uid is not None else None
    p2_info = info_map.get(p2_uid) if p2_uid is not None else None

    server_code = match_data.get("server_name", "USW")

    # High priority: DM both players with per-locale MatchInfoEmbed concurrently.
    dm_coros = []
    dm_uids: list[int] = []
    dm_views: list[MatchReportView1v1] = []
    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue

        try:
            user = await client.fetch_user(uid)
            logger.info("[WS] fetch_user OK", match_id=match_id, uid=uid)
        except Exception:
            logger.exception(
                "[WS] fetch_user FAILED for both_confirmed",
                match_id=match_id,
                uid=uid,
            )
            continue

        cache.active_match_info[uid] = {
            "match_data": match_data,
            "p1_info": p1_info,
            "p2_info": p2_info,
        }

        locale = get_player_locale(uid)
        info = info_map.get(uid)
        guide_visible = not bool(info and info.get("read_lobby_guide"))
        view = MatchReportView1v1(
            match_id,
            p1_name,
            p2_name,
            match_data,
            p1_info,
            p2_info,
            report_locked=ENABLE_REPLAY_VALIDATION,
            locale=locale,
            guide_visible=guide_visible,
        )
        dm_coros.append(
            queue_user_send_high(
                user,
                embeds=[
                    MatchInfoEmbed1v1(match_data, p1_info, p2_info, locale=locale),
                    LobbyGuideEmbed(server_code, locale=locale, visible=guide_visible),
                ],
                view=view,
            )
        )
        dm_uids.append(uid)
        dm_views.append(view)

    if dm_coros:
        results = await asyncio.gather(*dm_coros, return_exceptions=True)
        for uid, view, result in zip(dm_uids, dm_views, results):
            if isinstance(result, Exception):
                logger.error(
                    "[WS] DM delivery FAILED for both_confirmed",
                    match_id=match_id,
                    uid=uid,
                    error=str(result),
                )
            elif isinstance(result, discord.Message):
                view.message = result
                cache.active_match_messages[uid] = result
                logger.info(
                    "[WS] DM delivered for both_confirmed",
                    match_id=match_id,
                    uid=uid,
                )

    # The match-found messages already have view=None (both players pressed Confirm).
    for uid in (p1_uid, p2_uid):
        if uid is not None:
            cache.active_match_found_messages.pop(uid, None)

    logger.info("[WS] both_confirmed handler done", match_id=match_id)


async def _on_match_aborted(client: discord.Client, match_data: dict) -> None:
    """Notify both players that the match was aborted and post to match log.

    Player DMs and the match log channel both use the minimal (anonymous)
    embed so that neither party learns the other's identity.
    """
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")
    asyncio.create_task(activity_status.refresh_status_embed())

    # DEPRECATED: Full embeds with player names, races, and MMR.
    # Replaced by MatchAbortedMinimalEmbed to prevent leaking player
    # identities.  Kept here for reference in case we ever want to
    # restore detailed abort DMs behind a preference flag.
    #
    # p1_info = await _fetch_player_info(p1_uid) if p1_uid else None
    # p2_info = await _fetch_player_info(p2_uid) if p2_uid else None
    # await _send_to_both_localized(
    #     client, p1_uid, p2_uid, MatchAbortedEmbed, match_data, p1_info, p2_info
    # )

    await _clear_match_found_messages_low(p1_uid, p2_uid)
    await _send_to_both_minimal(client, p1_uid, p2_uid, match_data, "1v1", "aborted")
    await _clear_match_state_low(p1_uid, p2_uid)
    await _post_to_match_log_low(
        client, MatchAbortedMinimalEmbed(match_data, game_mode="1v1")
    )


async def _on_match_abandoned(client: discord.Client, match_data: dict) -> None:
    """Notify both players that the match was abandoned and post to match log.

    Player DMs and the match log channel both use the minimal (anonymous)
    embed so that neither party learns the other's identity.
    """
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")
    asyncio.create_task(activity_status.refresh_status_embed())

    # DEPRECATED: Full embeds with player names, races, and MMR.
    # Replaced by MatchAbandonedMinimalEmbed to prevent leaking player
    # identities.  Kept here for reference in case we ever want to
    # restore detailed abandon DMs behind a preference flag.
    #
    # p1_info = await _fetch_player_info(p1_uid) if p1_uid else None
    # p2_info = await _fetch_player_info(p2_uid) if p2_uid else None
    # await _send_to_both_localized(
    #     client, p1_uid, p2_uid, MatchAbandonedEmbed, match_data, p1_info, p2_info
    # )

    await _clear_match_found_messages_low(p1_uid, p2_uid)
    await _send_to_both_minimal(client, p1_uid, p2_uid, match_data, "1v1", "abandoned")
    await _clear_match_state_low(p1_uid, p2_uid)
    await _post_to_match_log_low(
        client, MatchAbandonedMinimalEmbed(match_data, game_mode="1v1")
    )


async def _on_match_completed(client: discord.Client, match_data: dict) -> None:
    """Notify both players of the completed match and post to match log."""
    match_id: int = match_data["id"]
    p1_uid = match_data.get("player_1_discord_uid")
    p2_uid = match_data.get("player_2_discord_uid")

    asyncio.create_task(
        activity_status.broadcast_match_completed(client, match_id, "1v1")
    )
    asyncio.create_task(activity_status.refresh_status_embed())

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
    for uid in leader_uids:
        cancel_deferred_ping(int(uid))
    asyncio.create_task(activity_status.broadcast_match_found(client, match_id, "2v2"))
    asyncio.create_task(activity_status.refresh_status_embed())
    cache = get_cache()
    logger.info(
        "[WS] match_found_2v2 handler start",
        match_id=match_id,
        leader_uids=leader_uids,
    )

    dm_coros = []
    dm_uids: list[int] = []
    dm_views: list[MatchFoundView2v2] = []
    for uid in leader_uids:
        try:
            user = await client.fetch_user(uid)
            logger.info("[WS] fetch_user OK", match_id=match_id, uid=uid)
            locale = get_player_locale(uid)
            view = MatchFoundView2v2(match_id, locale=locale)
            dm_coros.append(
                queue_user_send_high(
                    user,
                    embed=MatchFoundEmbed(match_data, locale=locale),
                    view=view,
                )
            )
            dm_uids.append(uid)
            dm_views.append(view)
        except Exception:
            logger.exception(
                "[WS] fetch_user FAILED for 2v2 match_found",
                match_id=match_id,
                uid=uid,
            )

    if dm_coros:
        results = await asyncio.gather(*dm_coros, return_exceptions=True)
        for uid, view, result in zip(dm_uids, dm_views, results):
            if isinstance(result, Exception):
                logger.error(
                    "[WS] DM delivery FAILED for 2v2 match_found",
                    match_id=match_id,
                    uid=uid,
                    error=str(result),
                )
            elif isinstance(result, discord.Message):
                view.message = result
                cache.active_match_found_messages[uid] = result
                logger.info(
                    "[WS] DM delivered for 2v2 match_found",
                    match_id=match_id,
                    uid=uid,
                )

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
    logger.info(
        "[WS] all_confirmed_2v2 handler start",
        match_id=match_id,
        uids=all_uids,
    )

    # Fetch player infos for all 4 players concurrently.
    info_results = await asyncio.gather(
        *(_fetch_player_info(uid) for uid in all_uids), return_exceptions=True
    )
    infos: dict[int, dict | None] = {}
    for uid, result in zip(all_uids, info_results):
        infos[uid] = result if isinstance(result, dict) else None

    dm_coros = []
    dm_uids: list[int] = []
    dm_views: list[MatchReportView2v2] = []
    for uid in all_uids:
        try:
            user = await client.fetch_user(uid)
            logger.info("[WS] fetch_user OK", match_id=match_id, uid=uid)
        except Exception:
            logger.exception(
                "[WS] fetch_user FAILED for 2v2 all_confirmed",
                match_id=match_id,
                uid=uid,
            )
            continue

        cache.active_match_info[uid] = {"match_data": match_data, "player_infos": infos}

        locale = get_player_locale(uid)
        info = infos.get(uid)
        guide_visible = not bool(info and info.get("read_lobby_guide"))
        view = MatchReportView2v2(
            match_id,
            match_data,
            infos,
            report_locked=ENABLE_REPLAY_VALIDATION,
            locale=locale,
            guide_visible=guide_visible,
        )
        dm_coros.append(
            queue_user_send_high(
                user,
                embeds=list(MatchInfoEmbeds2v2(match_data, infos, locale=locale))
                + [
                    LobbyGuideEmbed(
                        match_data.get("server_name", "USW"),
                        locale=locale,
                        visible=guide_visible,
                    )
                ],
                view=view,
            )
        )
        dm_uids.append(uid)
        dm_views.append(view)

    if dm_coros:
        dm_results = await asyncio.gather(*dm_coros, return_exceptions=True)
        for uid, view, dm_result in zip(dm_uids, dm_views, dm_results):
            if isinstance(dm_result, Exception):
                logger.error(
                    "[WS] DM delivery FAILED for 2v2 all_confirmed",
                    match_id=match_id,
                    uid=uid,
                    error=str(dm_result),
                )
            elif isinstance(dm_result, discord.Message):
                view.message = dm_result
                cache.active_match_messages[uid] = dm_result
                logger.info(
                    "[WS] DM delivered for 2v2 all_confirmed",
                    match_id=match_id,
                    uid=uid,
                )

    for uid in all_uids:
        cache.active_match_found_messages.pop(uid, None)

    logger.info("[WS] all_confirmed_2v2 handler done", match_id=match_id)


async def _on_match_aborted_2v2(client: discord.Client, match_data: dict) -> None:
    all_uids = _get_2v2_uids(match_data)
    asyncio.create_task(activity_status.refresh_status_embed())

    # DEPRECATED: Full embeds with player names, races, and MMR.
    # Replaced by MatchAbortedMinimalEmbed to prevent leaking player
    # identities.  Kept here for reference in case we ever want to
    # restore detailed abort DMs behind a preference flag.
    #
    # player_infos = await _fetch_player_infos_2v2(all_uids)
    # await _send_to_all_2v2_localized(
    #     client, all_uids, MatchAbortedEmbed2v2, match_data, player_infos
    # )

    await _send_to_all_minimal(client, all_uids, match_data, "2v2", "aborted")
    await _clear_match_state_all_2v2(all_uids)
    await _post_to_match_log_low(
        client, MatchAbortedMinimalEmbed(match_data, game_mode="2v2")
    )


async def _on_match_abandoned_2v2(client: discord.Client, match_data: dict) -> None:
    all_uids = _get_2v2_uids(match_data)
    asyncio.create_task(activity_status.refresh_status_embed())

    # DEPRECATED: Full embeds with player names, races, and MMR.
    # Replaced by MatchAbandonedMinimalEmbed to prevent leaking player
    # identities.  Kept here for reference in case we ever want to
    # restore detailed abandon DMs behind a preference flag.
    #
    # player_infos = await _fetch_player_infos_2v2(all_uids)
    # await _send_to_all_2v2_localized(
    #     client, all_uids, MatchAbandonedEmbed2v2, match_data, player_infos
    # )

    await _send_to_all_minimal(client, all_uids, match_data, "2v2", "abandoned")
    await _clear_match_state_all_2v2(all_uids)
    await _post_to_match_log_low(
        client, MatchAbandonedMinimalEmbed(match_data, game_mode="2v2")
    )


async def _on_match_completed_2v2(client: discord.Client, match_data: dict) -> None:
    match_id: int = match_data["id"]
    all_uids = _get_2v2_uids(match_data)
    asyncio.create_task(
        activity_status.broadcast_match_completed(client, match_id, "2v2")
    )
    asyncio.create_task(activity_status.refresh_status_embed())
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


async def _send_to_both_minimal(
    client: discord.Client,
    p1_uid: int | None,
    p2_uid: int | None,
    match_data: dict,
    game_mode: str,
    kind: str,
) -> None:
    """DM both 1v1 players with a per-locale minimal (anonymous) abort/abandon embed."""
    embed_cls = (
        MatchAbortedMinimalEmbed if kind == "aborted" else MatchAbandonedMinimalEmbed
    )
    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue
        try:
            locale = get_player_locale(uid)
            user = await client.fetch_user(uid)
            await queue_user_send_low(
                user,
                embed=embed_cls(match_data, game_mode=game_mode, locale=locale),
            )
        except Exception:
            logger.exception(f"[WS] Failed to DM user {uid}")


async def _send_to_all_minimal(
    client: discord.Client,
    uids: list[int],
    match_data: dict,
    game_mode: str,
    kind: str,
) -> None:
    """DM all 2v2 players with a per-locale minimal (anonymous) abort/abandon embed."""
    embed_cls = (
        MatchAbortedMinimalEmbed if kind == "aborted" else MatchAbandonedMinimalEmbed
    )
    for uid in uids:
        try:
            locale = get_player_locale(uid)
            user = await client.fetch_user(uid)
            await queue_user_send_low(
                user,
                embed=embed_cls(match_data, game_mode=game_mode, locale=locale),
            )
        except Exception:
            logger.exception(f"[WS] Failed to DM 2v2 user {uid}")


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


async def _clear_match_state_low(
    p1_uid: int | None,
    p2_uid: int | None,
) -> None:
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
