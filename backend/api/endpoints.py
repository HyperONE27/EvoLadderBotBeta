import asyncio
import structlog
from typing import Any

import httpx

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from backend.api.dependencies import get_backend, get_ws_manager
from backend.api.websocket import ConnectionManager
from backend.core.config import (
    CHANNEL_DELETION_DELAY_SECONDS,
    CHANNEL_MANAGER_URL,
    COERCE_INDETERMINATE_AS_LOSS,
    CURRENT_SEASON,
)
from backend.algorithms.replay_parser import parse_replay_1v1, parse_replay_2v2
from backend.algorithms.replay_verifier import verify_replay_1v1, verify_replay_2v2
from backend.lookups.admin_lookups import get_admin_by_discord_uid
from backend.lookups.replay_1v1_lookups import get_replays_1v1_by_match_id
from common.config import ACTIVITY_ANALYTICS_MAX_RANGE_DAYS
from common.datetime_helpers import ensure_utc, utc_now
from backend.api.models import (
    AdminBanRequest,
    AdminBanResponse,
    AdminMatch2v2Response,
    AdminMatchResponse,
    AdminStatusResetRequest,
    AdminStatusResetResponse,
    AdminResolveRequest,
    AdminResolveResponse,
    ActiveMatchSnapshotRow,
    ActiveMatchSnapshot2v2Row,
    AdminSnapshot2v2Response,
    PartySnapshotRow,
    AdminSnapshotResponse,
    AdminsResponse,
    LeaderboardEntry,
    LeaderboardEntry2v2Model,
    LeaderboardResponse,
    LeaderboardResponse2v2,
    GreetingResponse,
    GuildMemberJoinRequest,
    GuildMemberJoinResponse,
    Match2v2AbortRequest,
    Match2v2AbortResponse,
    Match2v2ConfirmRequest,
    Match2v2ConfirmResponse,
    Match2v2ReportRequest,
    Match2v2ReportResponse,
    MatchAbortRequest,
    MatchAbortResponse,
    MatchConfirmRequest,
    MatchConfirmResponse,
    Matches1v1Response,
    MatchReportRequest,
    MatchReportResponse,
    MMRs1v1AllResponse,
    MMRs1v1Response,
    NotificationsOut,
    NotificationsUpsertRequest,
    OwnerSetMMRRequest,
    OwnerSetMMRResponse,
    OwnerToggleAdminRequest,
    OwnerToggleAdminResponse,
    PartyInfoResponse,
    PartyInviteRequest,
    PartyInviteResponse,
    PartyLeaveRequest,
    PartyLeaveResponse,
    PartyRespondRequest,
    PartyRespondResponse,
    PlayerNameAvailabilityResponse,
    PlayerRegisterRequest,
    PlayerRegisterResponse,
    ToggleLobbyGuideResponse,
    PlayersResponse,
    Preferences1v1Response,
    Preferences2v2Response,
    Preferences2v2UpsertRequest,
    Preferences2v2UpsertResponse,
    PreferencesUpsertRequest,
    PreferencesUpsertResponse,
    Profile2v2PartnerEntry,
    ProfileMmrEntry,
    ProfileResponse,
    Queue2v2JoinRequest,
    Queue2v2JoinResponse,
    Queue2v2LeaveRequest,
    Queue2v2LeaveResponse,
    Queue2v2StatsResponse,
    QueueJoinAnalyticsBucket,
    QueueJoinAnalyticsResponse,
    QueueJoinRequest,
    QueueJoinResponse,
    QueueLeaveRequest,
    QueueLeaveResponse,
    QueueStatsResponse,
    ReplayUploadResponse,
    SetCountryConfirmRequest,
    SetCountryConfirmResponse,
    SetupConfirmRequest,
    SetupSurveyRequest,
    SetupConfirmResponse,
    TermsOfServiceConfirmRequest,
    TermsOfServiceConfirmResponse,
    ActivePlayersResponse,
    ReferralRequest,
    ReferralResponse,
)
from backend.core.bootstrap import Backend
from backend.domain_types.ephemeral import LeaderboardEntry1v1, LeaderboardEntry2v2

logger = structlog.get_logger(__name__)

router = APIRouter()


async def _delayed_pool_check(app: Backend, delay: float) -> None:
    """Fire-and-forget: wait *delay* seconds, then verify the process pool."""
    await asyncio.sleep(delay)
    try:
        await app.ensure_pool_healthy()
    except Exception:
        logger.exception("Delayed pool health check failed")


def _entry_to_model(e: LeaderboardEntry1v1) -> LeaderboardEntry:
    return LeaderboardEntry(
        discord_uid=e["discord_uid"],
        player_name=e["player_name"],
        ordinal_rank=e["ordinal_rank"],
        active_ordinal_rank=e["active_ordinal_rank"],
        letter_rank=e["letter_rank"],
        race=e["race"],
        nationality=e["nationality"],
        mmr=e["mmr"],
        games_played=e["games_played"],
        games_won=e["games_won"],
        games_lost=e["games_lost"],
        games_drawn=e["games_drawn"],
        last_played_at=(
            e["last_played_at"].isoformat() if e["last_played_at"] else None
        ),
    )


def _entry_to_model_2v2(e: LeaderboardEntry2v2) -> LeaderboardEntry2v2Model:
    return LeaderboardEntry2v2Model(
        player_1_discord_uid=e["player_1_discord_uid"],
        player_2_discord_uid=e["player_2_discord_uid"],
        player_1_name=e["player_1_name"],
        player_2_name=e["player_2_name"],
        player_1_nationality=e["player_1_nationality"],
        player_2_nationality=e["player_2_nationality"],
        ordinal_rank=e["ordinal_rank"],
        active_ordinal_rank=e["active_ordinal_rank"],
        letter_rank=e["letter_rank"],
        mmr=e["mmr"],
        games_played=e["games_played"],
        games_won=e["games_won"],
        games_lost=e["games_lost"],
        games_drawn=e["games_drawn"],
        last_played_at=(
            e["last_played_at"].isoformat() if e["last_played_at"] else None
        ),
    )


async def _broadcast_leaderboard_if_dirty(app: Backend, ws: ConnectionManager) -> None:
    """If the leaderboard was rebuilt since the last check, broadcast both."""
    if app.orchestrator.consume_leaderboard_dirty():
        entries_1v1 = app.orchestrator.get_leaderboard_1v1()
        entries_2v2 = app.orchestrator.get_leaderboard_2v2()
        await ws.broadcast(
            "leaderboard_updated",
            {
                "leaderboard": [_entry_to_model(e).model_dump() for e in entries_1v1],
                "leaderboard_2v2": [
                    _entry_to_model_2v2(e).model_dump() for e in entries_2v2
                ],
            },
        )


async def _request_channel_create(
    match_id: int,
    match_mode: str,
    discord_uids: list[int],
    ws: ConnectionManager,
) -> None:
    """Call the channel manager to create a talk channel, then broadcast the URL via WS.

    Runs as an asyncio.create_task fire-and-forget; failures are logged and swallowed
    so they never block the match lifecycle.
    """
    if CHANNEL_MANAGER_URL is None:
        return
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{CHANNEL_MANAGER_URL}/channels/create",
                json={
                    "match_id": match_id,
                    "match_mode": match_mode,
                    "discord_uids": discord_uids,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        await ws.broadcast(
            "talk_channel_created",
            {
                "match_id": match_id,
                "game_mode": match_mode,
                "discord_uids": discord_uids,
                "channel_id": data["channel_id"],
                "message_url": data["message_url"],
            },
        )
        logger.info(f"[ChannelManager] Talk channel created for match #{match_id}")
    except Exception:
        logger.warning(
            f"[ChannelManager] Channel create request failed for match #{match_id}",
            exc_info=True,
        )


async def _request_channel_delete(match_id: int, match_mode: str) -> None:
    """Ask the channel manager to delete the talk channel for a concluded match.

    Fire-and-forget; 404 (no channel exists) is silently ignored.
    """
    if CHANNEL_MANAGER_URL is None:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.delete(
                f"{CHANNEL_MANAGER_URL}/channels/by_match/{match_id}",
                params={
                    "match_mode": match_mode,
                    "delay_seconds": CHANNEL_DELETION_DELAY_SECONDS,
                },
            )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return  # no channel was ever created — normal for matches before this feature
        logger.warning(
            f"[ChannelManager] Channel delete request failed for match #{match_id}",
            exc_info=True,
        )
    except Exception:
        logger.warning(
            f"[ChannelManager] Channel delete request failed for match #{match_id}",
            exc_info=True,
        )


@router.get("/commands/greet/{discord_uid}", response_model=GreetingResponse)
async def greet(
    discord_uid: int,
    app: Backend = Depends(get_backend),
) -> GreetingResponse:
    app.orchestrator.log_event(
        {
            "discord_uid": discord_uid,
            "event_type": "player_command",
            "action": "greeting",
            "event_data": {},
        }
    )
    return GreetingResponse(message=f"👋 Hello, {discord_uid}!")


# --- /events/guild_member_join ---


@router.post("/events/guild_member_join", response_model=GuildMemberJoinResponse)
async def guild_member_join(
    request: GuildMemberJoinRequest,
    app: Backend = Depends(get_backend),
) -> GuildMemberJoinResponse:
    app.orchestrator.log_event(
        {
            "discord_uid": 2,  # bot process sentinel
            "event_type": "system_event",
            "action": "guild_member_join",
            "game_mode": None,
            "match_id": None,
            "target_discord_uid": request.discord_uid,
            "event_data": {
                "discord_username": request.discord_username,
                "account_age_days": request.account_age_days,
            },
        }
    )
    return GuildMemberJoinResponse(ok=True)


# --- /admins/{discord_uid} ---


@router.get("/admins/{discord_uid}", response_model=AdminsResponse)
async def get_admin(
    discord_uid: int,
    app: Backend = Depends(get_backend),
) -> AdminsResponse:
    return AdminsResponse(admin=app.orchestrator.get_admin(discord_uid))


# --- /admin ban ---


@router.put("/admin/ban", response_model=AdminBanResponse)
async def admin_ban(
    request: AdminBanRequest,
    app: Backend = Depends(get_backend),
) -> AdminBanResponse:
    success, new_is_banned = app.orchestrator.toggle_ban(request.discord_uid)
    if not success:
        raise HTTPException(status_code=404, detail="Player not found.")
    app.orchestrator.log_event(
        {
            "discord_uid": request.admin_discord_uid,
            "event_type": "admin_command",
            "action": "ban",
            "target_discord_uid": request.discord_uid,
            "event_data": {
                "target_discord_uid": request.discord_uid,
                "new_is_banned": new_is_banned,
            },
        }
    )
    return AdminBanResponse(success=True, new_is_banned=new_is_banned)


# --- /admin statusreset ---


@router.put("/admin/statusreset", response_model=AdminStatusResetResponse)
async def admin_statusreset(
    request: AdminStatusResetRequest,
    app: Backend = Depends(get_backend),
) -> AdminStatusResetResponse:
    success, error, old_status = app.orchestrator.reset_player_status(
        request.discord_uid
    )
    if not success:
        code = 404 if "not found" in (error or "").lower() else 409
        raise HTTPException(status_code=code, detail=error)
    app.orchestrator.log_event(
        {
            "discord_uid": request.admin_discord_uid,
            "event_type": "admin_command",
            "action": "statusreset",
            "target_discord_uid": request.discord_uid,
            "event_data": {
                "target_discord_uid": request.discord_uid,
                "old_status": old_status,
            },
        }
    )
    return AdminStatusResetResponse(success=True, old_status=old_status)


# --- /admin match ---


@router.get("/admin/matches_1v1/{match_id}", response_model=AdminMatchResponse)
async def admin_match(
    match_id: int,
    caller_uid: int = Query(...),
    app: Backend = Depends(get_backend),
) -> AdminMatchResponse:
    match = app.orchestrator.get_match_1v1(match_id)

    # Look up player rows and resolving admin.
    player_1 = None
    player_2 = None
    admin = None
    if match is not None:
        player_1 = app.orchestrator.get_player(match["player_1_discord_uid"])
        player_2 = app.orchestrator.get_player(match["player_2_discord_uid"])
        admin_uid = match.get("admin_discord_uid")
        if admin_uid is not None:
            admin = get_admin_by_discord_uid(admin_uid)

    replays = get_replays_1v1_by_match_id(match_id) or []

    # Run verification on each replay.
    verifications: list[dict | None] = []
    replay_urls: list[str | None] = []
    season_maps = app.state_manager.maps.get("1v1", {}).get(CURRENT_SEASON, {})

    for replay in replays:
        replay_urls.append(replay.get("replay_path"))
        if match is not None:
            verification = verify_replay_1v1(
                dict(replay), dict(match), app.state_manager.mods, season_maps
            )
            verifications.append(verification)
        else:
            verifications.append(None)

    app.orchestrator.log_event(
        {
            "discord_uid": caller_uid,
            "event_type": "admin_command",
            "action": "match_view",
            "match_id": match_id,
            "event_data": {"match_id": match_id},
        }
    )
    return AdminMatchResponse(
        match=match,
        player_1=player_1,
        player_2=player_2,
        admin=admin,
        replays=replays,
        verification=verifications,
        replay_urls=replay_urls,
    )


# --- /admin resolve ---


@router.put(
    "/admin/matches_1v1/{match_id}/resolve", response_model=AdminResolveResponse
)
async def admin_resolve(
    match_id: int,
    request: AdminResolveRequest,
    app: Backend = Depends(get_backend),
    ws: ConnectionManager = Depends(get_ws_manager),
) -> AdminResolveResponse:
    result = app.orchestrator.admin_resolve_match(
        match_id, request.result, request.admin_discord_uid
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=404, detail=result.get("error", "Match not found.")
        )
    app.orchestrator.log_event(
        {
            "discord_uid": request.admin_discord_uid,
            "event_type": "admin_command",
            "action": "resolve",
            "game_mode": "1v1",
            "match_id": match_id,
            "event_data": {
                "game_mode": "1v1",
                "match_id": match_id,
                "result": request.result,
            },
        }
    )
    asyncio.create_task(_request_channel_delete(match_id, "1v1"))
    await _broadcast_leaderboard_if_dirty(app, ws)
    return AdminResolveResponse(success=True, data=result)


# --- /admin match 2v2 ---


@router.get("/admin/matches_2v2/{match_id}", response_model=AdminMatch2v2Response)
async def admin_match_2v2(
    match_id: int,
    caller_uid: int = Query(...),
    app: Backend = Depends(get_backend),
) -> AdminMatch2v2Response:
    match = app.orchestrator.get_match_2v2(match_id)

    t1_p1 = t1_p2 = t2_p1 = t2_p2 = None
    admin = None
    if match is not None:
        t1_p1 = app.orchestrator.get_player(match["team_1_player_1_discord_uid"])
        t1_p2 = app.orchestrator.get_player(match["team_1_player_2_discord_uid"])
        t2_p1 = app.orchestrator.get_player(match["team_2_player_1_discord_uid"])
        t2_p2 = app.orchestrator.get_player(match["team_2_player_2_discord_uid"])
        admin_uid = match.get("admin_discord_uid")
        if admin_uid is not None:
            admin = get_admin_by_discord_uid(admin_uid)

    app.orchestrator.log_event(
        {
            "discord_uid": caller_uid,
            "event_type": "admin_command",
            "action": "match_view",
            "game_mode": "2v2",
            "match_id": match_id,
            "event_data": {"game_mode": "2v2", "match_id": match_id},
        }
    )
    return AdminMatch2v2Response(
        match=match,
        team_1_player_1=t1_p1,
        team_1_player_2=t1_p2,
        team_2_player_1=t2_p1,
        team_2_player_2=t2_p2,
        admin=admin,
    )


# --- /admin resolve 2v2 ---


@router.put(
    "/admin/matches_2v2/{match_id}/resolve", response_model=AdminResolveResponse
)
async def admin_resolve_2v2(
    match_id: int,
    request: AdminResolveRequest,
    app: Backend = Depends(get_backend),
    ws: ConnectionManager = Depends(get_ws_manager),
) -> AdminResolveResponse:
    result = app.orchestrator.admin_resolve_match_2v2(
        match_id, request.result, request.admin_discord_uid
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=404, detail=result.get("error", "Match not found.")
        )
    # Add rank letters (leaderboard was just rebuilt inside admin_resolve_match_2v2)
    # and key aliases so the bot can pass the dict directly to MatchFinalizedEmbed2v2.
    result = app.orchestrator.enrich_match_2v2_with_ranks(result)
    result["id"] = result.get("match_id")
    result["match_result"] = result.get("result")
    app.orchestrator.log_event(
        {
            "discord_uid": request.admin_discord_uid,
            "event_type": "admin_command",
            "action": "resolve",
            "game_mode": "2v2",
            "match_id": match_id,
            "event_data": {
                "game_mode": "2v2",
                "match_id": match_id,
                "result": request.result,
            },
        }
    )
    asyncio.create_task(_request_channel_delete(match_id, "2v2"))
    await _broadcast_leaderboard_if_dirty(app, ws)
    return AdminResolveResponse(success=True, data=result)


# --- /admin snapshot ---


@router.get("/admin/snapshot_1v1", response_model=AdminSnapshotResponse)
async def admin_snapshot(
    caller_uid: int = Query(...),
    app: Backend = Depends(get_backend),
) -> AdminSnapshotResponse:
    queue = app.orchestrator.get_queue_snapshot_1v1()
    active_raw = app.orchestrator.get_active_matches_snapshot_1v1()
    active = [ActiveMatchSnapshotRow.model_validate(r) for r in active_raw]

    # DataFrame memory stats.
    sm = app.state_manager
    stats: dict[str, dict[str, object]] = {}
    for attr_name in dir(sm):
        if attr_name.endswith("_df"):
            df = getattr(sm, attr_name)
            if hasattr(df, "estimated_size"):
                table = attr_name.removesuffix("_df")
                stats[table] = {
                    "rows": len(df),
                    "size_mb": round(df.estimated_size("mb"), 3),
                }

    app.orchestrator.log_event(
        {
            "discord_uid": caller_uid,
            "event_type": "admin_command",
            "action": "snapshot",
            "event_data": {},
        }
    )
    return AdminSnapshotResponse(
        queue=queue,
        active_matches=active,
        dataframe_stats=stats,
    )


@router.get("/admin/snapshot_2v2", response_model=AdminSnapshot2v2Response)
async def admin_snapshot_2v2(
    caller_uid: int = Query(...),
    app: Backend = Depends(get_backend),
) -> AdminSnapshot2v2Response:
    queue = app.orchestrator.get_queue_snapshot_2v2()
    active_raw = app.orchestrator.get_active_matches_snapshot_2v2()
    active = [ActiveMatchSnapshot2v2Row.model_validate(r) for r in active_raw]
    parties = [
        PartySnapshotRow.model_validate(p)
        for p in app.orchestrator.get_parties_snapshot()
    ]

    sm = app.state_manager
    stats: dict[str, dict[str, object]] = {}
    for attr_name in dir(sm):
        if attr_name.endswith("_df"):
            df = getattr(sm, attr_name)
            if hasattr(df, "estimated_size"):
                table = attr_name.removesuffix("_df")
                stats[table] = {
                    "rows": len(df),
                    "size_mb": round(df.estimated_size("mb"), 3),
                }

    app.orchestrator.log_event(
        {
            "discord_uid": caller_uid,
            "event_type": "admin_command",
            "action": "snapshot_2v2",
            "event_data": {},
        }
    )
    return AdminSnapshot2v2Response(
        queue=queue,
        active_matches=active,
        parties=parties,
        dataframe_stats=stats,
    )


# --- /owner admin ---


@router.put("/owner/admin", response_model=OwnerToggleAdminResponse)
async def owner_toggle_admin(
    request: OwnerToggleAdminRequest,
    app: Backend = Depends(get_backend),
) -> OwnerToggleAdminResponse:
    result = app.orchestrator.toggle_admin_role(
        request.discord_uid, request.discord_username
    )
    if not result.get("success"):
        raise HTTPException(status_code=403, detail=result.get("error", "Forbidden."))
    app.orchestrator.log_event(
        {
            "discord_uid": request.owner_discord_uid,
            "event_type": "owner_command",
            "action": "admin_toggle",
            "target_discord_uid": request.discord_uid,
            "event_data": {
                "target_discord_uid": request.discord_uid,
                "action": result.get("action"),
                "new_role": result.get("new_role"),
            },
        }
    )
    return OwnerToggleAdminResponse(**result)


# --- /owner mmr ---


@router.put("/owner/mmr", response_model=OwnerSetMMRResponse)
async def owner_set_mmr(
    request: OwnerSetMMRRequest,
    app: Backend = Depends(get_backend),
    ws: ConnectionManager = Depends(get_ws_manager),
) -> OwnerSetMMRResponse:
    success, old_mmr = app.orchestrator.admin_set_mmr(
        request.discord_uid, request.race, request.new_mmr
    )
    if not success:
        raise HTTPException(status_code=404, detail="Player MMR row not found.")
    app.orchestrator.log_event(
        {
            "discord_uid": request.owner_discord_uid,
            "event_type": "owner_command",
            "action": "set_mmr",
            "target_discord_uid": request.discord_uid,
            "event_data": {
                "target_discord_uid": request.discord_uid,
                "race": request.race,
                "old_mmr": old_mmr,
                "new_mmr": request.new_mmr,
            },
        }
    )
    await _broadcast_leaderboard_if_dirty(app, ws)
    return OwnerSetMMRResponse(success=True, old_mmr=old_mmr)


# --- /help ---

# --- /leaderboard ---


@router.get("/leaderboard_1v1", response_model=LeaderboardResponse)
async def leaderboard_1v1(
    caller_uid: int = Query(...),
    app: Backend = Depends(get_backend),
) -> LeaderboardResponse:
    entries = app.orchestrator.get_leaderboard_1v1()
    app.orchestrator.log_event(
        {
            "discord_uid": caller_uid,
            "event_type": "player_command",
            "action": "leaderboard",
            "event_data": {},
        }
    )
    return LeaderboardResponse(leaderboard=[_entry_to_model(e) for e in entries])


@router.get("/leaderboard_2v2", response_model=LeaderboardResponse2v2)
async def leaderboard_2v2(
    caller_uid: int = Query(...),
    app: Backend = Depends(get_backend),
) -> LeaderboardResponse2v2:
    entries = app.orchestrator.get_leaderboard_2v2()
    app.orchestrator.log_event(
        {
            "discord_uid": caller_uid,
            "event_type": "player_command",
            "action": "leaderboard",
            "event_data": {"game_mode": "2v2"},
        }
    )
    return LeaderboardResponse2v2(leaderboard=[_entry_to_model_2v2(e) for e in entries])


# --- /profile ---


@router.get("/profile/{discord_uid}", response_model=ProfileResponse)
async def profile(
    discord_uid: int,
    app: Backend = Depends(get_backend),
) -> ProfileResponse:
    player, mmrs_1v1_raw, mmrs_2v2_raw, notifications_row = (
        app.orchestrator.get_profile(discord_uid)
    )
    mmrs_1v1 = [ProfileMmrEntry.model_validate(r) for r in mmrs_1v1_raw]
    mmrs_2v2 = [Profile2v2PartnerEntry.model_validate(r) for r in mmrs_2v2_raw]
    notifications = (
        _notification_row_to_out(dict(notifications_row)) if notifications_row else None
    )
    app.orchestrator.log_event(
        {
            "discord_uid": discord_uid,
            "event_type": "player_command",
            "action": "profile",
            "event_data": {},
        }
    )
    return ProfileResponse(
        player=player, mmrs_1v1=mmrs_1v1, mmrs_2v2=mmrs_2v2, notifications=notifications
    )


# --- /prune ---

# --- /queue ---


def _notification_row_to_out(row: dict[str, Any]) -> NotificationsOut:
    def _ts(val: Any) -> str | None:
        if val is None:
            return None
        return val.isoformat() if hasattr(val, "isoformat") else str(val)

    return NotificationsOut(
        id=int(row["id"]),
        discord_uid=int(row["discord_uid"]),
        read_quick_start_guide=bool(row["read_quick_start_guide"]),
        notify_queue_1v1=bool(row["notify_queue_1v1"]),
        notify_queue_1v1_cooldown=int(row["notify_queue_1v1_cooldown"]),
        notify_queue_1v1_last_sent=_ts(row.get("notify_queue_1v1_last_sent")),
        notify_queue_2v2=bool(row["notify_queue_2v2"]),
        notify_queue_2v2_cooldown=int(row["notify_queue_2v2_cooldown"]),
        notify_queue_2v2_last_sent=_ts(row.get("notify_queue_2v2_last_sent")),
        notify_queue_ffa=bool(row["notify_queue_ffa"]),
        notify_queue_ffa_cooldown=int(row["notify_queue_ffa_cooldown"]),
        notify_queue_ffa_last_sent=_ts(row.get("notify_queue_ffa_last_sent")),
        updated_at=_ts(row.get("updated_at")),
    )


@router.get("/analytics/queue_joins", response_model=QueueJoinAnalyticsResponse)
async def analytics_queue_joins(
    start: str = Query(..., description="ISO 8601 range start (UTC)"),
    end: str = Query(..., description="ISO 8601 range end (UTC)"),
    game_mode: str = Query("1v1"),
    bucket_minutes: int | None = Query(None, ge=1, le=1440),
    app: Backend = Depends(get_backend),
) -> QueueJoinAnalyticsResponse:
    if game_mode not in ("1v1", "2v2", "FFA"):
        raise HTTPException(status_code=400, detail="Invalid game_mode")
    st = ensure_utc(start)
    en = ensure_utc(end)
    if st is None or en is None:
        raise HTTPException(status_code=400, detail="Invalid start or end datetime")
    if st >= en:
        raise HTTPException(status_code=400, detail="start must be before end")
    max_delta = ACTIVITY_ANALYTICS_MAX_RANGE_DAYS * 24 * 3600
    if (en - st).total_seconds() > max_delta:
        raise HTTPException(
            status_code=400,
            detail=f"Range too large (max {ACTIVITY_ANALYTICS_MAX_RANGE_DAYS} days)",
        )

    bucket_m, buckets = app.orchestrator.get_queue_join_analytics(
        st,
        en,
        game_mode,
        bucket_minutes=bucket_minutes,
    )
    return QueueJoinAnalyticsResponse(
        game_mode=game_mode,
        bucket_minutes=bucket_m,
        buckets=[QueueJoinAnalyticsBucket(**b) for b in buckets],
    )


# --- /referral ---


@router.post("/referral", response_model=ReferralResponse)
async def submit_referral(
    req: ReferralRequest,
    app: Backend = Depends(get_backend),
) -> ReferralResponse:
    success, payload = app.orchestrator.submit_referral(
        req.discord_uid, req.referral_code
    )
    if success:
        return ReferralResponse(success=True, referrer_player_name=payload)
    return ReferralResponse(success=False, error=payload)


@router.get("/stats/active_players", response_model=ActivePlayersResponse)
async def stats_active_players(
    app: Backend = Depends(get_backend),
) -> ActivePlayersResponse:
    return ActivePlayersResponse(
        active_player_count=app.orchestrator.get_active_player_count()
    )


@router.get("/notifications/{discord_uid}", response_model=NotificationsOut)
async def get_notifications(
    discord_uid: int,
    app: Backend = Depends(get_backend),
) -> NotificationsOut:
    row = app.orchestrator.ensure_notifications(discord_uid)
    return _notification_row_to_out(row)


@router.put("/notifications", response_model=NotificationsOut)
async def put_notifications(
    request: NotificationsUpsertRequest,
    app: Backend = Depends(get_backend),
) -> NotificationsOut:
    if (
        request.notify_queue_1v1 is None
        and request.notify_queue_2v2 is None
        and request.notify_queue_ffa is None
        and request.notify_queue_1v1_cooldown is None
        and request.notify_queue_2v2_cooldown is None
        and request.notify_queue_ffa_cooldown is None
    ):
        raise HTTPException(status_code=400, detail="No preference fields to update")
    app.orchestrator.ensure_notifications(request.discord_uid)
    row = app.orchestrator.upsert_notifications(
        request.discord_uid,
        notify_queue_1v1=request.notify_queue_1v1,
        notify_queue_2v2=request.notify_queue_2v2,
        notify_queue_ffa=request.notify_queue_ffa,
        notify_queue_1v1_cooldown=request.notify_queue_1v1_cooldown,
        notify_queue_2v2_cooldown=request.notify_queue_2v2_cooldown,
        notify_queue_ffa_cooldown=request.notify_queue_ffa_cooldown,
    )
    return _notification_row_to_out(row)


@router.put("/surveys/setup", status_code=204)
async def put_setup_survey(
    request: SetupSurveyRequest,
    app: Backend = Depends(get_backend),
) -> None:
    app.orchestrator.save_setup_survey(
        request.discord_uid,
        q1=request.setup_q1_response,
        q2=request.setup_q2_response,
        q3=request.setup_q3_response,
        q4=request.setup_q4_response,
    )


@router.post("/queue_1v1/join", response_model=QueueJoinResponse)
async def queue_join(
    request: QueueJoinRequest,
    app: Backend = Depends(get_backend),
    ws: ConnectionManager = Depends(get_ws_manager),
) -> QueueJoinResponse:
    success, message = app.orchestrator.join_queue_1v1(
        request.discord_uid,
        request.discord_username,
        request.bw_race,
        request.sc2_race,
        request.bw_mmr,
        request.sc2_mmr,
        request.map_vetoes,
    )
    if not success:
        code = 400 if message and "race" in message.lower() else 409
        raise HTTPException(status_code=code, detail=message)
    app.orchestrator.log_event(
        {
            "discord_uid": request.discord_uid,
            "event_type": "player_command",
            "action": "queue_join",
            "game_mode": "1v1",
            "event_data": {
                "bw_race": request.bw_race,
                "sc2_race": request.sc2_race,
                "bw_mmr": request.bw_mmr,
                "sc2_mmr": request.sc2_mmr,
                "map_vetoes": request.map_vetoes,
            },
        }
    )
    await app.broadcast_queue_join_activity_if_needed(ws, request.discord_uid, "1v1")
    return QueueJoinResponse(success=True, message=None)


@router.delete("/queue_1v1/leave", response_model=QueueLeaveResponse)
async def queue_leave(
    request: QueueLeaveRequest,
    app: Backend = Depends(get_backend),
) -> QueueLeaveResponse:
    success, message = app.orchestrator.leave_queue_1v1(request.discord_uid)
    if not success:
        raise HTTPException(status_code=409, detail=message)
    app.orchestrator.log_event(
        {
            "discord_uid": request.discord_uid,
            "event_type": "player_command",
            "action": "queue_leave",
            "game_mode": "1v1",
            "event_data": {},
        }
    )
    return QueueLeaveResponse(success=True, message=None)


@router.get("/queue_1v1/stats", response_model=QueueStatsResponse)
async def queue_stats(
    app: Backend = Depends(get_backend),
) -> QueueStatsResponse:
    stats = app.orchestrator.get_queue_stats()
    return QueueStatsResponse(**stats)


# --- /queue_2v2 ---


@router.get("/queue_2v2/stats", response_model=Queue2v2StatsResponse)
async def queue_stats_2v2(
    app: Backend = Depends(get_backend),
) -> Queue2v2StatsResponse:
    stats = app.orchestrator.get_queue_stats_2v2()
    return Queue2v2StatsResponse(**stats)


@router.post("/queue_2v2/join", response_model=Queue2v2JoinResponse)
async def queue_2v2_join(
    request: Queue2v2JoinRequest,
    app: Backend = Depends(get_backend),
    ws: ConnectionManager = Depends(get_ws_manager),
) -> Queue2v2JoinResponse:
    success, message = app.orchestrator.join_queue_2v2(
        request.discord_uid,
        request.discord_username,
        request.pure_bw_leader_race,
        request.pure_bw_member_race,
        request.mixed_leader_race,
        request.mixed_member_race,
        request.pure_sc2_leader_race,
        request.pure_sc2_member_race,
        request.map_vetoes,
    )
    if not success:
        code = 400 if message and "race" in message.lower() else 409
        raise HTTPException(status_code=code, detail=message)
    app.orchestrator.log_event(
        {
            "discord_uid": request.discord_uid,
            "event_type": "player_command",
            "action": "queue_join",
            "game_mode": "2v2",
            "event_data": {
                "pure_bw_leader_race": request.pure_bw_leader_race,
                "pure_bw_member_race": request.pure_bw_member_race,
                "mixed_leader_race": request.mixed_leader_race,
                "mixed_member_race": request.mixed_member_race,
                "pure_sc2_leader_race": request.pure_sc2_leader_race,
                "pure_sc2_member_race": request.pure_sc2_member_race,
                "map_vetoes": request.map_vetoes,
            },
        }
    )
    await app.broadcast_queue_join_activity_if_needed(ws, request.discord_uid, "2v2")
    return Queue2v2JoinResponse(success=True, message=None)


@router.delete("/queue_2v2/leave", response_model=Queue2v2LeaveResponse)
async def queue_2v2_leave(
    request: Queue2v2LeaveRequest,
    app: Backend = Depends(get_backend),
) -> Queue2v2LeaveResponse:
    success, message = app.orchestrator.leave_queue_2v2(request.discord_uid)
    if not success:
        raise HTTPException(status_code=409, detail=message)
    app.orchestrator.log_event(
        {
            "discord_uid": request.discord_uid,
            "event_type": "player_command",
            "action": "queue_leave",
            "game_mode": "2v2",
            "event_data": {},
        }
    )
    return Queue2v2LeaveResponse(success=True, message=None)


# --- /preferences_1v1 ---


@router.get("/preferences_1v1/{discord_uid}", response_model=Preferences1v1Response)
async def get_preferences(
    discord_uid: int,
    app: Backend = Depends(get_backend),
) -> Preferences1v1Response:
    prefs = app.orchestrator.get_preferences_1v1(discord_uid)
    return Preferences1v1Response(preferences=prefs)


@router.put("/preferences_1v1", response_model=PreferencesUpsertResponse)
async def upsert_preferences(
    request: PreferencesUpsertRequest,
    app: Backend = Depends(get_backend),
) -> PreferencesUpsertResponse:
    app.orchestrator.upsert_preferences_1v1(
        request.discord_uid,
        request.last_chosen_races,
        request.last_chosen_vetoes,
    )
    return PreferencesUpsertResponse(success=True)


# --- /preferences_2v2 ---


@router.get("/preferences_2v2/{discord_uid}", response_model=Preferences2v2Response)
async def get_preferences_2v2(
    discord_uid: int,
    app: Backend = Depends(get_backend),
) -> Preferences2v2Response:
    prefs = app.orchestrator.get_preferences_2v2(discord_uid)
    return Preferences2v2Response(preferences=prefs)


@router.put("/preferences_2v2", response_model=Preferences2v2UpsertResponse)
async def upsert_preferences_2v2(
    request: Preferences2v2UpsertRequest,
    app: Backend = Depends(get_backend),
) -> Preferences2v2UpsertResponse:
    app.orchestrator.upsert_preferences_2v2(
        request.discord_uid,
        request.last_pure_bw_leader_race,
        request.last_pure_bw_member_race,
        request.last_mixed_leader_race,
        request.last_mixed_member_race,
        request.last_pure_sc2_leader_race,
        request.last_pure_sc2_member_race,
        request.last_chosen_vetoes,
    )
    return Preferences2v2UpsertResponse(success=True)


# --- /matches_1v1 actions ---


@router.put("/matches_1v1/{match_id}/confirm", response_model=MatchConfirmResponse)
async def match_confirm(
    match_id: int,
    request: MatchConfirmRequest,
    app: Backend = Depends(get_backend),
    ws: ConnectionManager = Depends(get_ws_manager),
) -> MatchConfirmResponse:
    success, both_confirmed = app.orchestrator.confirm_match(
        match_id, request.discord_uid
    )
    if both_confirmed:
        match = app.orchestrator.get_match_1v1(match_id)
        if match is not None:
            enriched = app.orchestrator.enrich_match_with_ranks(dict(match))
            await ws.broadcast("both_confirmed", enriched)
            uids = [
                uid
                for uid in [
                    enriched.get("player_1_discord_uid"),
                    enriched.get("player_2_discord_uid"),
                ]
                if uid is not None
            ]
            asyncio.create_task(_request_channel_create(match_id, "1v1", uids, ws))
    app.orchestrator.log_event(
        {
            "discord_uid": request.discord_uid,
            "event_type": "player_command",
            "action": "match_confirm",
            "game_mode": "1v1",
            "match_id": match_id,
            "event_data": {"game_mode": "1v1", "match_id": match_id},
        }
    )
    return MatchConfirmResponse(success=True, both_confirmed=both_confirmed)


@router.put("/matches_1v1/{match_id}/abort", response_model=MatchAbortResponse)
async def match_abort(
    match_id: int,
    request: MatchAbortRequest,
    app: Backend = Depends(get_backend),
    ws: ConnectionManager = Depends(get_ws_manager),
) -> MatchAbortResponse:
    success, message = app.orchestrator.abort_match(match_id, request.discord_uid)
    if not success:
        if "not found" in (message or "").lower():
            code = 404
        elif "not part" in (message or "").lower():
            code = 403
        else:
            code = 409
        raise HTTPException(status_code=code, detail=message)
    match = app.orchestrator.get_match_1v1(match_id)
    if match is not None:
        enriched = app.orchestrator.enrich_match_with_ranks(dict(match))
        await ws.broadcast("match_aborted", enriched)
    app.orchestrator.log_event(
        {
            "discord_uid": request.discord_uid,
            "event_type": "player_command",
            "action": "match_abort",
            "game_mode": "1v1",
            "match_id": match_id,
            "event_data": {"game_mode": "1v1", "match_id": match_id},
        }
    )
    return MatchAbortResponse(success=True, message=None)


@router.put("/matches_1v1/{match_id}/report", response_model=MatchReportResponse)
async def match_report(
    match_id: int,
    request: MatchReportRequest,
    app: Backend = Depends(get_backend),
    ws: ConnectionManager = Depends(get_ws_manager),
) -> MatchReportResponse:
    success, message, match = app.orchestrator.report_match_result(
        match_id, request.discord_uid, request.report
    )
    if not success:
        if "Invalid report" in (message or ""):
            code = 400
        elif "not found" in (message or "").lower():
            code = 404
        elif "not part" in (message or "").lower():
            code = 403
        else:
            code = 409
        raise HTTPException(status_code=code, detail=message)
    if match is not None:
        result = match.get("match_result")
        enriched = app.orchestrator.enrich_match_with_ranks(dict(match))
        if result == "conflict":
            await ws.broadcast("match_conflict", enriched)
            asyncio.create_task(_request_channel_delete(match_id, "1v1"))
        elif result is not None:
            await ws.broadcast("match_completed", enriched)
            asyncio.create_task(_request_channel_delete(match_id, "1v1"))
        await _broadcast_leaderboard_if_dirty(app, ws)
    app.orchestrator.log_event(
        {
            "discord_uid": request.discord_uid,
            "event_type": "player_command",
            "action": "match_report",
            "game_mode": "1v1",
            "match_id": match_id,
            "event_data": {
                "game_mode": "1v1",
                "match_id": match_id,
                "report": request.report,
            },
        }
    )
    return MatchReportResponse(success=True, message=message, match=match)


# --- /matches_2v2 ---


@router.put("/matches_2v2/{match_id}/confirm", response_model=Match2v2ConfirmResponse)
async def match_2v2_confirm(
    match_id: int,
    request: Match2v2ConfirmRequest,
    app: Backend = Depends(get_backend),
    ws: ConnectionManager = Depends(get_ws_manager),
) -> Match2v2ConfirmResponse:
    success, all_confirmed = app.orchestrator.confirm_match_2v2(
        match_id, request.discord_uid
    )
    if not success:
        match = app.orchestrator.get_match_2v2(match_id)
        if match is None:
            raise HTTPException(status_code=404, detail="Match not found.")
        raise HTTPException(status_code=403, detail="Player is not part of this match.")
    if all_confirmed:
        match = app.orchestrator.get_match_2v2(match_id)
        if match is not None:
            enriched = app.orchestrator.enrich_match_2v2_with_ranks(dict(match))
            await ws.broadcast("both_confirmed", {"game_mode": "2v2", **enriched})
            uids = [
                uid
                for uid in [
                    enriched.get("team_1_player_1_discord_uid"),
                    enriched.get("team_1_player_2_discord_uid"),
                    enriched.get("team_2_player_1_discord_uid"),
                    enriched.get("team_2_player_2_discord_uid"),
                ]
                if uid is not None
            ]
            asyncio.create_task(_request_channel_create(match_id, "2v2", uids, ws))
    app.orchestrator.log_event(
        {
            "discord_uid": request.discord_uid,
            "event_type": "player_command",
            "action": "match_confirm",
            "game_mode": "2v2",
            "match_id": match_id,
            "event_data": {"game_mode": "2v2", "match_id": match_id},
        }
    )
    return Match2v2ConfirmResponse(success=True, all_confirmed=all_confirmed)


@router.put("/matches_2v2/{match_id}/abort", response_model=Match2v2AbortResponse)
async def match_2v2_abort(
    match_id: int,
    request: Match2v2AbortRequest,
    app: Backend = Depends(get_backend),
    ws: ConnectionManager = Depends(get_ws_manager),
) -> Match2v2AbortResponse:
    success, message = app.orchestrator.abort_match_2v2(match_id, request.discord_uid)
    if not success:
        if "not found" in (message or "").lower():
            code = 404
        elif "not part" in (message or "").lower():
            code = 403
        else:
            code = 409
        raise HTTPException(status_code=code, detail=message)
    match = app.orchestrator.get_match_2v2(match_id)
    if match is not None:
        enriched = app.orchestrator.enrich_match_2v2_with_ranks(dict(match))
        await ws.broadcast("match_aborted", {"game_mode": "2v2", **enriched})
    app.orchestrator.log_event(
        {
            "discord_uid": request.discord_uid,
            "event_type": "player_command",
            "action": "match_abort",
            "game_mode": "2v2",
            "match_id": match_id,
            "event_data": {"game_mode": "2v2", "match_id": match_id},
        }
    )
    return Match2v2AbortResponse(success=True, message=None)


@router.put("/matches_2v2/{match_id}/report", response_model=Match2v2ReportResponse)
async def match_2v2_report(
    match_id: int,
    request: Match2v2ReportRequest,
    app: Backend = Depends(get_backend),
    ws: ConnectionManager = Depends(get_ws_manager),
) -> Match2v2ReportResponse:
    success, message, match = app.orchestrator.report_match_result_2v2(
        match_id, request.discord_uid, request.report
    )
    if not success:
        if "Invalid report" in (message or ""):
            code = 400
        elif "not found" in (message or "").lower():
            code = 404
        elif "not part" in (message or "").lower():
            code = 403
        else:
            code = 409
        raise HTTPException(status_code=code, detail=message)
    if match is not None:
        result = match.get("match_result")
        enriched = app.orchestrator.enrich_match_2v2_with_ranks(dict(match))
        if result == "conflict":
            await ws.broadcast("match_conflict", {"game_mode": "2v2", **enriched})
            asyncio.create_task(_request_channel_delete(match_id, "2v2"))
        elif result is not None:
            await ws.broadcast("match_completed", {"game_mode": "2v2", **enriched})
            asyncio.create_task(_request_channel_delete(match_id, "2v2"))
        await _broadcast_leaderboard_if_dirty(app, ws)
    app.orchestrator.log_event(
        {
            "discord_uid": request.discord_uid,
            "event_type": "player_command",
            "action": "match_report",
            "game_mode": "2v2",
            "match_id": match_id,
            "event_data": {
                "game_mode": "2v2",
                "match_id": match_id,
                "report": request.report,
            },
        }
    )
    return Match2v2ReportResponse(success=True, message=message, match=match)


# --- /setcountry ---


@router.put("/commands/setcountry")
async def setcountry(
    request: SetCountryConfirmRequest,
    app: Backend = Depends(get_backend),
) -> SetCountryConfirmResponse:
    success, message = app.orchestrator.setcountry(
        request.discord_uid,
        request.discord_username,
        request.country_code,
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    app.orchestrator.log_event(
        {
            "discord_uid": request.discord_uid,
            "event_type": "player_command",
            "action": "setcountry",
            "event_data": {"country_code": request.country_code},
        }
    )
    return SetCountryConfirmResponse(success=True, message=message)


# --- /setup ---
@router.put("/commands/setup")
async def setup(
    request: SetupConfirmRequest,
    app: Backend = Depends(get_backend),
) -> SetupConfirmResponse:
    success, message = app.orchestrator.setup(
        request.discord_uid,
        request.discord_username,
        request.player_name,
        request.alt_player_names,
        request.battletag,
        request.nationality,
        request.location,
        request.language,
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    app.orchestrator.log_event(
        {
            "discord_uid": request.discord_uid,
            "event_type": "player_command",
            "action": "setup",
            "event_data": {
                "player_name": request.player_name,
                "battletag": request.battletag,
                "nationality": request.nationality,
                "location": request.location,
                "language": request.language,
            },
        }
    )
    return SetupConfirmResponse(success=True, message=message)


# --- /termsofservice ---


@router.put("/commands/termsofservice")
async def termsofservice(
    request: TermsOfServiceConfirmRequest,
    app: Backend = Depends(get_backend),
) -> TermsOfServiceConfirmResponse:
    success, message = app.orchestrator.set_tos(
        request.discord_uid,
        request.discord_username,
        request.accepted,
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    app.orchestrator.log_event(
        {
            "discord_uid": request.discord_uid,
            "event_type": "player_command",
            "action": "termsofservice",
            "event_data": {"accepted": request.accepted},
        }
    )
    return TermsOfServiceConfirmResponse(success=True, message=message)


# --- General endpoints ---


@router.get(
    "/players/player_name_availability",
    response_model=PlayerNameAvailabilityResponse,
)
async def player_name_availability(
    player_name: str,
    exclude_discord_uid: int | None = None,
    app: Backend = Depends(get_backend),
) -> PlayerNameAvailabilityResponse:
    available = app.orchestrator.is_player_name_available(
        player_name, exclude_discord_uid
    )
    return PlayerNameAvailabilityResponse(available=available)


@router.get("/players/by_name/{name}", response_model=PlayersResponse)
async def players_by_name(
    name: str,
    app: Backend = Depends(get_backend),
) -> PlayersResponse:
    player = app.orchestrator.get_player_by_string(name)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found.")
    return PlayersResponse(player=player)


@router.post("/players/register", response_model=PlayerRegisterResponse)
async def register_player(
    request: PlayerRegisterRequest,
    app: Backend = Depends(get_backend),
) -> PlayerRegisterResponse:
    was_created = app.orchestrator.register_player(
        request.discord_uid, request.discord_username
    )
    return PlayerRegisterResponse(created=was_created)


@router.post(
    "/players/{discord_uid}/toggle_lobby_guide",
    response_model=ToggleLobbyGuideResponse,
)
async def toggle_lobby_guide(
    discord_uid: int,
    app: Backend = Depends(get_backend),
) -> ToggleLobbyGuideResponse:
    success, new_value = app.orchestrator.toggle_lobby_guide(discord_uid)
    return ToggleLobbyGuideResponse(success=success, new_value=new_value)


@router.get("/players/{discord_uid}", response_model=PlayersResponse)
async def players(
    discord_uid: int,
    app: Backend = Depends(get_backend),
) -> PlayersResponse:
    return PlayersResponse(player=app.orchestrator.get_player(discord_uid))


@router.get("/matches_1v1/{match_id}", response_model=Matches1v1Response)
async def matches_1v1(
    match_id: int,
    app: Backend = Depends(get_backend),
) -> Matches1v1Response:
    return Matches1v1Response(match=app.orchestrator.get_match_1v1(match_id))


@router.get("/mmrs_1v1/{discord_uid}", response_model=MMRs1v1AllResponse)
async def mmrs_1v1_all(
    discord_uid: int,
    app: Backend = Depends(get_backend),
) -> MMRs1v1AllResponse:
    return MMRs1v1AllResponse(mmrs=app.orchestrator.get_mmrs_1v1(discord_uid))


@router.get("/mmrs_1v1/{discord_uid}/{race}", response_model=MMRs1v1Response)
async def mmrs_1v1(
    discord_uid: int,
    race: str,
    app: Backend = Depends(get_backend),
) -> MMRs1v1Response:
    return MMRs1v1Response(mmr=app.orchestrator.get_mmr_1v1(discord_uid, race))


# --- /matches_1v1/{match_id}/replay ---


@router.post(
    "/matches_1v1/{match_id}/replay",
    response_model=ReplayUploadResponse,
)
async def upload_replay(
    match_id: int,
    discord_uid: int = Form(...),
    replay_file: UploadFile = File(...),
    app: Backend = Depends(get_backend),
    ws: ConnectionManager = Depends(get_ws_manager),
) -> ReplayUploadResponse:
    """
    Accept a .SC2Replay upload from a match participant.

    Flow:
      1. Validate the match and player.
      2. Parse the replay in the process pool (non-blocking).
      3. Insert a ``pending`` row in ``replays_1v1`` (DB then cache).
      4. Upload bytes to Supabase Storage (up to 3 attempts).
      5. Update ``upload_status`` to ``completed`` / ``failed``.
      6. Update the match row with the replay reference.
      7. Run verification and return everything to the bot.
    """
    # --- 1. Validate ---
    match = app.orchestrator.get_match_1v1(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found.")

    p1_uid = match["player_1_discord_uid"]
    p2_uid = match["player_2_discord_uid"]
    if discord_uid not in (p1_uid, p2_uid):
        raise HTTPException(
            status_code=403, detail="You are not a participant in this match."
        )
    player_num = 1 if discord_uid == p1_uid else 2

    # --- 2. Parse in process pool ---
    await app.ensure_pool_healthy()
    replay_bytes = await replay_file.read()
    loop = asyncio.get_running_loop()
    try:
        parsed: dict = await loop.run_in_executor(
            app.process_pool, parse_replay_1v1, replay_bytes
        )
    except Exception as exc:
        logger.exception("Replay parse executor failed", match_id=match_id)
        raise HTTPException(
            status_code=500, detail=f"Replay parse executor failed: {exc}"
        )
    asyncio.create_task(_delayed_pool_check(app, delay=10.0))

    if parsed.get("error"):
        raise HTTPException(status_code=422, detail=parsed["error"])

    # --- 3. Build paths and insert pending row ---
    uploaded_at = utc_now()
    replay_hash = parsed["replay_hash"]
    filename = f"{uploaded_at.strftime('%Y-%m-%d_%H-%M-%S-%f')}_{replay_hash}.SC2Replay"
    storage_path = f"1v1/{match_id}/{discord_uid}/{filename}"

    created = app.orchestrator.insert_replay_1v1_pending(
        match_id=match_id,
        discord_uid=discord_uid,
        parsed=parsed,
        initial_path=storage_path,
        uploaded_at=uploaded_at,
    )
    replay_id: int = created["id"]

    # --- 4. Upload to Supabase Storage (up to 3 attempts) ---
    public_url: str | None = None
    upload_status = "failed"

    for attempt in range(3):
        public_url = await loop.run_in_executor(
            None, app.storage_writer.upload_replay, replay_bytes, storage_path
        )
        if public_url:
            upload_status = "completed"
            break
        logger.warning(
            "Supabase Storage upload attempt %d/3 failed",
            attempt + 1,
            match_id=match_id,
            replay_id=replay_id,
        )

    # --- 5. Update upload_status (and final path if upload succeeded) ---
    final_path: str = public_url if public_url is not None else storage_path
    app.orchestrator.update_replay_status(replay_id, upload_status, final_path)

    # --- 6. Update the match row ---
    app.orchestrator.update_match_replay_refs(
        match_id, player_num, final_path, replay_id, uploaded_at
    )

    # --- 7. Verify ---
    season_maps = app.state_manager.maps.get("1v1", {}).get(CURRENT_SEASON, {})
    verification = verify_replay_1v1(
        parsed, dict(match), app.state_manager.mods, season_maps
    )

    # --- 8. Attempt auto-resolution if verification passes ---
    auto_resolved = False
    resolved_match = None

    # Re-fetch the match in case it was resolved while we were uploading.
    current_match = app.orchestrator.get_match_1v1(match_id)
    replay_result_1v1: str | None = parsed.get("match_result")
    is_determinate_1v1 = replay_result_1v1 in (
        "player_1_win",
        "player_2_win",
        "draw",
    )
    is_indeterminate_1v1 = not is_determinate_1v1 and COERCE_INDETERMINATE_AS_LOSS

    can_auto_resolve = (
        current_match is not None
        and current_match["match_result"] is None
        and verification.get("races", {}).get("success", False)
        and verification.get("map", {}).get("success", False)
        and verification.get("timestamp", {}).get("success", False)
        and verification.get("ai_players", {}).get("success", True)
        and (is_determinate_1v1 or is_indeterminate_1v1)
    )

    if can_auto_resolve and current_match is not None:
        if is_indeterminate_1v1:
            # Coerce indeterminate as a loss for the uploading player.
            if discord_uid == current_match["player_1_discord_uid"]:
                match_result: str | None = "player_2_win"
            else:
                match_result = "player_1_win"
        else:
            # Map the replay result (in replay player order) to match player order
            # using the winning race.
            replay_result_val: str = parsed["match_result"]
            match_result = _map_replay_result_to_match(
                replay_result_val, parsed, dict(current_match)
            )

        if match_result is not None:
            resolved_match_row = app.orchestrator.replay_auto_resolve_match(
                match_id, discord_uid, match_result
            )
            resolved_match = dict(resolved_match_row)
            auto_resolved = True

            # Broadcast match_completed + leaderboard via WebSocket.
            resolved_match = app.orchestrator.enrich_match_with_ranks(resolved_match)
            await ws.broadcast("match_completed", resolved_match)
            asyncio.create_task(_request_channel_delete(match_id, "1v1"))
            await _broadcast_leaderboard_if_dirty(app, ws)

            logger.info(
                "Replay auto-resolved match",
                match_id=match_id,
                result=match_result,
                uploader=discord_uid,
            )

    app.orchestrator.log_event(
        {
            "discord_uid": discord_uid,
            "event_type": "player_command",
            "action": "replay_upload",
            "game_mode": "1v1",
            "match_id": match_id,
            "event_data": {
                "game_mode": "1v1",
                "match_id": match_id,
                "upload_status": upload_status,
                "auto_resolved": auto_resolved,
                "replay_id": replay_id,
            },
        }
    )
    return ReplayUploadResponse(
        success=True,
        parsed=parsed,
        verification=verification,
        replay_id=replay_id,
        upload_status=upload_status,
        auto_resolved=auto_resolved,
        match=resolved_match,
    )


def _map_replay_result_to_match(
    replay_result: str,
    parsed: dict,
    match: dict,
) -> str | None:
    """Map a replay result (in replay player order) to match player order.

    Since BW-vs-SC2 matchups guarantee different races for each player,
    we identify the winning race from the replay and find which match
    player had that race.

    Returns the result in match-player terms, or None if the mapping fails.
    """
    if replay_result == "draw":
        return "draw"

    # Determine the winning race from the replay.
    if replay_result == "player_1_win":
        winning_race = parsed["player_1_race"]
    elif replay_result == "player_2_win":
        winning_race = parsed["player_2_race"]
    else:
        return None

    # Map to match player order.
    if winning_race == match["player_1_race"]:
        return "player_1_win"
    elif winning_race == match["player_2_race"]:
        return "player_2_win"
    else:
        # Race not found in match — should not happen if races check passed.
        return None


# --- /matches_2v2/{match_id}/replay ---


@router.post(
    "/matches_2v2/{match_id}/replay",
    response_model=ReplayUploadResponse,
)
async def upload_replay_2v2(
    match_id: int,
    discord_uid: int = Form(...),
    replay_file: UploadFile = File(...),
    app: Backend = Depends(get_backend),
    ws: ConnectionManager = Depends(get_ws_manager),
) -> ReplayUploadResponse:
    """
    Accept a .SC2Replay upload from a 2v2 match participant.

    Same 8-step flow as 1v1 but:
      - Validates against all 4 participants and determines team_num.
      - Uses ``parse_replay_2v2`` / ``verify_replay_2v2``.
      - Auto-resolve maps replay result to team_1_win / team_2_win.
    """
    # --- 1. Validate ---
    match = app.orchestrator.get_match_2v2(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found.")

    team_1_uids = (
        match["team_1_player_1_discord_uid"],
        match["team_1_player_2_discord_uid"],
    )
    team_2_uids = (
        match["team_2_player_1_discord_uid"],
        match["team_2_player_2_discord_uid"],
    )

    if discord_uid in team_1_uids:
        team_num = 1
    elif discord_uid in team_2_uids:
        team_num = 2
    else:
        raise HTTPException(
            status_code=403, detail="You are not a participant in this match."
        )

    # --- 2. Parse in process pool ---
    await app.ensure_pool_healthy()
    replay_bytes = await replay_file.read()
    loop = asyncio.get_running_loop()
    try:
        parsed: dict = await loop.run_in_executor(
            app.process_pool, parse_replay_2v2, replay_bytes
        )
    except Exception as exc:
        logger.exception("2v2 replay parse executor failed", match_id=match_id)
        raise HTTPException(
            status_code=500, detail=f"Replay parse executor failed: {exc}"
        )
    asyncio.create_task(_delayed_pool_check(app, delay=10.0))

    if parsed.get("error"):
        raise HTTPException(status_code=422, detail=parsed["error"])

    # --- 3. Build paths and insert pending row ---
    uploaded_at = utc_now()
    replay_hash = parsed["replay_hash"]
    filename = f"{uploaded_at.strftime('%Y-%m-%d_%H-%M-%S-%f')}_{replay_hash}.SC2Replay"
    storage_path = f"2v2/{match_id}/{discord_uid}/{filename}"

    created = app.orchestrator.insert_replay_2v2_pending(
        match_id=match_id,
        discord_uid=discord_uid,
        parsed=parsed,
        initial_path=storage_path,
        uploaded_at=uploaded_at,
    )
    replay_id: int = created["id"]

    # --- 4. Upload to Supabase Storage (up to 3 attempts) ---
    public_url: str | None = None
    upload_status = "failed"

    for attempt in range(3):
        public_url = await loop.run_in_executor(
            None, app.storage_writer.upload_replay, replay_bytes, storage_path
        )
        if public_url:
            upload_status = "completed"
            break
        logger.warning(
            "Supabase Storage upload attempt %d/3 failed",
            attempt + 1,
            match_id=match_id,
            replay_id=replay_id,
        )

    # --- 5. Update upload_status (and final path if upload succeeded) ---
    final_path: str = public_url if public_url is not None else storage_path
    app.orchestrator.update_replay_2v2_status(replay_id, upload_status, final_path)

    # --- 6. Update the match row ---
    app.orchestrator.update_match_2v2_replay_refs(
        match_id, team_num, final_path, replay_id, uploaded_at
    )

    # --- 7. Verify ---
    season_maps = app.state_manager.maps.get("2v2", {}).get(CURRENT_SEASON, {})
    verification = verify_replay_2v2(
        parsed, dict(match), app.state_manager.mods, season_maps
    )

    # --- 8. Attempt auto-resolution if verification passes ---
    auto_resolved = False
    resolved_match = None

    # Re-fetch in case the match was resolved while we were uploading.
    current_match = app.orchestrator.get_match_2v2(match_id)

    replay_result_2v2: str | None = parsed.get("match_result")
    is_determinate_2v2 = replay_result_2v2 in ("team_1_win", "team_2_win", "draw")
    is_indeterminate_2v2 = not is_determinate_2v2 and COERCE_INDETERMINATE_AS_LOSS

    races_pass_2v2 = verification.get("races_team_1", {}).get(
        "success", False
    ) and verification.get("races_team_2", {}).get("success", False)
    can_auto_resolve = (
        current_match is not None
        and current_match["match_result"] is None
        and races_pass_2v2
        and verification.get("map", {}).get("success", False)
        and verification.get("timestamp", {}).get("success", False)
        and verification.get("ai_players", {}).get("success", True)
        and (is_determinate_2v2 or is_indeterminate_2v2)
    )

    if can_auto_resolve and current_match is not None:
        if is_indeterminate_2v2:
            # Coerce indeterminate as a loss for the uploading player's team.
            match_result_2v2: str = "team_2_win" if team_num == 1 else "team_1_win"
        else:
            match_result_2v2 = parsed["match_result"]
        resolved_match_row = app.orchestrator.replay_auto_resolve_match_2v2(
            match_id, discord_uid, match_result_2v2
        )
        resolved_match = dict(resolved_match_row)
        auto_resolved = True

        # Broadcast match_completed + leaderboard via WebSocket.
        resolved_match["game_mode"] = "2v2"
        await ws.broadcast("match_completed", resolved_match)
        asyncio.create_task(_request_channel_delete(match_id, "2v2"))
        await _broadcast_leaderboard_if_dirty(app, ws)

        logger.info(
            "2v2 replay auto-resolved match",
            match_id=match_id,
            result=match_result_2v2,
            uploader=discord_uid,
        )

    app.orchestrator.log_event(
        {
            "discord_uid": discord_uid,
            "event_type": "player_command",
            "action": "replay_upload",
            "game_mode": "2v2",
            "match_id": match_id,
            "event_data": {
                "game_mode": "2v2",
                "match_id": match_id,
                "upload_status": upload_status,
                "auto_resolved": auto_resolved,
                "replay_id": replay_id,
            },
        }
    )
    return ReplayUploadResponse(
        success=True,
        parsed=parsed,
        verification=verification,
        replay_id=replay_id,
        upload_status=upload_status,
        auto_resolved=auto_resolved,
        match=resolved_match,
    )


# ---------------------------------------------------------------------------
# Party 2v2
# ---------------------------------------------------------------------------


@router.put("/party_2v2/invite", response_model=PartyInviteResponse)
async def party_invite(
    request: PartyInviteRequest,
    app: Backend = Depends(get_backend),
) -> PartyInviteResponse:
    success, error = app.orchestrator.create_party_invite(
        request.inviter_discord_uid,
        request.inviter_player_name,
        request.invitee_discord_uid,
        request.invitee_player_name,
    )
    if not success:
        raise HTTPException(status_code=409, detail=error)
    return PartyInviteResponse(success=True)


@router.put("/party_2v2/respond", response_model=PartyRespondResponse)
async def party_respond(
    request: PartyRespondRequest,
    app: Backend = Depends(get_backend),
) -> PartyRespondResponse:
    success, error, invite = app.orchestrator.respond_to_party_invite(
        request.invitee_discord_uid,
        request.accepted,
    )
    if not success:
        raise HTTPException(status_code=409, detail=error)
    return PartyRespondResponse(
        success=True,
        inviter_discord_uid=invite["inviter_discord_uid"] if invite else None,
        inviter_player_name=invite["inviter_player_name"] if invite else None,
        invitee_discord_uid=invite["invitee_discord_uid"] if invite else None,
        invitee_player_name=invite["invitee_player_name"] if invite else None,
    )


@router.delete("/party_2v2/leave", response_model=PartyLeaveResponse)
async def party_leave(
    request: PartyLeaveRequest,
    app: Backend = Depends(get_backend),
) -> PartyLeaveResponse:
    success, error, partner_uid = app.orchestrator.leave_party(request.discord_uid)
    if not success:
        raise HTTPException(status_code=409, detail=error)
    return PartyLeaveResponse(success=True, partner_discord_uid=partner_uid)


@router.get("/party_2v2/{discord_uid}", response_model=PartyInfoResponse)
async def party_info(
    discord_uid: int,
    app: Backend = Depends(get_backend),
) -> PartyInfoResponse:
    party = app.orchestrator.get_party(discord_uid)
    if party is None:
        return PartyInfoResponse(in_party=False)
    return PartyInfoResponse(
        in_party=True,
        leader_discord_uid=party["leader_discord_uid"],
        leader_player_name=party["leader_player_name"],
        member_discord_uid=party["member_discord_uid"],
        member_player_name=party["member_player_name"],
        created_at=party["created_at"],
    )
