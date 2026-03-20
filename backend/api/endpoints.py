import asyncio
import structlog
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from backend.api.dependencies import get_backend, get_ws_manager
from backend.api.websocket import ConnectionManager
from backend.core.config import CURRENT_SEASON
from backend.algorithms.replay_parser import parse_replay
from backend.algorithms.replay_verifier import verify_replay
from backend.lookups.admin_lookups import get_admin_by_discord_uid
from backend.lookups.replay_1v1_lookups import get_replays_1v1_by_match_id
from common.config import ACTIVITY_ANALYTICS_MAX_RANGE_DAYS
from common.datetime_helpers import ensure_utc, utc_now
from backend.api.models import (
    AdminBanRequest,
    AdminBanResponse,
    AdminMatchResponse,
    AdminStatusResetRequest,
    AdminStatusResetResponse,
    AdminResolveRequest,
    AdminResolveResponse,
    ActiveMatchSnapshotRow,
    AdminSnapshotResponse,
    AdminsResponse,
    LeaderboardEntry,
    LeaderboardResponse,
    GreetingResponse,
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
    PlayersResponse,
    Preferences1v1Response,
    PreferencesUpsertRequest,
    PreferencesUpsertResponse,
    ProfileMmrEntry,
    ProfileResponse,
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
    SetupConfirmResponse,
    TermsOfServiceConfirmRequest,
    TermsOfServiceConfirmResponse,
)
from backend.core.bootstrap import Backend
from backend.domain_types.ephemeral import LeaderboardEntry1v1

logger = structlog.get_logger(__name__)

router = APIRouter()


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


async def _broadcast_leaderboard_if_dirty(app: Backend, ws: ConnectionManager) -> None:
    """If the leaderboard was rebuilt since the last check, broadcast it."""
    if app.orchestrator.consume_leaderboard_dirty():
        entries = app.orchestrator.get_leaderboard_1v1()
        models = [_entry_to_model(e) for e in entries]
        await ws.broadcast(
            "leaderboard_updated",
            {"leaderboard": [m.model_dump() for m in models]},
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
            verification = verify_replay(
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


# --- /profile ---


@router.get("/profile/{discord_uid}", response_model=ProfileResponse)
async def profile(
    discord_uid: int,
    app: Backend = Depends(get_backend),
) -> ProfileResponse:
    player, mmrs_raw = app.orchestrator.get_profile(discord_uid)
    mmrs = [ProfileMmrEntry.model_validate(r) for r in mmrs_raw]
    app.orchestrator.log_event(
        {
            "discord_uid": discord_uid,
            "event_type": "player_command",
            "action": "profile",
            "event_data": {},
        }
    )
    return ProfileResponse(player=player, mmrs_1v1=mmrs)


# --- /prune ---

# --- /queue ---


def _notification_row_to_out(row: dict[str, Any]) -> NotificationsOut:
    ua = row.get("updated_at")
    ua_str: str | None
    if ua is None:
        ua_str = None
    elif hasattr(ua, "isoformat"):
        ua_str = ua.isoformat()
    else:
        ua_str = str(ua)
    return NotificationsOut(
        id=int(row["id"]),
        discord_uid=int(row["discord_uid"]),
        read_quick_start_guide=bool(row["read_quick_start_guide"]),
        notify_queue_1v1=bool(row["notify_queue_1v1"]),
        notify_queue_2v2=bool(row["notify_queue_2v2"]),
        notify_queue_ffa=bool(row["notify_queue_ffa"]),
        queue_notify_cooldown_minutes=int(row["queue_notify_cooldown_minutes"]),
        updated_at=ua_str,
    )


@router.get("/analytics/queue_joins", response_model=QueueJoinAnalyticsResponse)
async def analytics_queue_joins(
    start: str = Query(..., description="ISO 8601 range start (UTC)"),
    end: str = Query(..., description="ISO 8601 range end (UTC)"),
    game_mode: str = Query("1v1"),
    dedupe: bool = Query(False),
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
        dedupe=dedupe,
    )
    return QueueJoinAnalyticsResponse(
        game_mode=game_mode,
        bucket_minutes=bucket_m,
        dedupe=dedupe,
        buckets=[QueueJoinAnalyticsBucket(**b) for b in buckets],
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
        and request.queue_notify_cooldown_minutes is None
    ):
        raise HTTPException(status_code=400, detail="No preference fields to update")
    app.orchestrator.ensure_notifications(request.discord_uid)
    row = app.orchestrator.upsert_notifications(
        request.discord_uid,
        notify_queue_1v1=request.notify_queue_1v1,
        notify_queue_2v2=request.notify_queue_2v2,
        notify_queue_ffa=request.notify_queue_ffa,
        queue_notify_cooldown_minutes=request.queue_notify_cooldown_minutes,
    )
    return _notification_row_to_out(row)


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
        elif result is not None:
            await ws.broadcast("match_completed", enriched)
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
    replay_bytes = await replay_file.read()
    loop = asyncio.get_running_loop()
    try:
        parsed: dict = await loop.run_in_executor(
            app.process_pool, parse_replay, replay_bytes
        )
    except Exception as exc:
        logger.exception("Replay parse executor failed", match_id=match_id)
        raise HTTPException(
            status_code=500, detail=f"Replay parse executor failed: {exc}"
        )

    if parsed.get("error"):
        raise HTTPException(status_code=422, detail=parsed["error"])

    # --- 3. Build paths and insert pending row ---
    uploaded_at = utc_now()
    replay_hash = parsed["replay_hash"]
    filename = f"{uploaded_at.strftime('%Y-%m-%d_%H-%M-%S-%f')}_{replay_hash}.SC2Replay"
    storage_path = f"replays/{match_id}/{discord_uid}/{filename}"

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
    verification = verify_replay(
        parsed, dict(match), app.state_manager.mods, season_maps
    )

    # --- 8. Attempt auto-resolution if verification passes ---
    auto_resolved = False
    resolved_match = None

    # Re-fetch the match in case it was resolved while we were uploading.
    current_match = app.orchestrator.get_match_1v1(match_id)
    can_auto_resolve = (
        current_match is not None
        and current_match["match_result"] is None
        and verification.get("races", {}).get("success", False)
        and verification.get("map", {}).get("success", False)
        and verification.get("timestamp", {}).get("success", False)
        and verification.get("ai_players", {}).get("success", True)
        and parsed.get("match_result") in ("player_1_win", "player_2_win", "draw")
    )

    if can_auto_resolve and current_match is not None:
        # Map the replay result (in replay player order) to match player order
        # using the winning race.
        replay_result: str = parsed["match_result"]
        match_result = _map_replay_result_to_match(
            replay_result, parsed, dict(current_match)
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
