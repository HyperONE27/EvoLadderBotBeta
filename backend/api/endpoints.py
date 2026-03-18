import asyncio
import structlog
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, UploadFile

from backend.api.dependencies import get_backend
from backend.algorithms.replay_parser import parse_replay
from backend.algorithms.replay_verifier import verify_replay
from backend.api.models import (
    AdminBanRequest,
    AdminBanResponse,
    AdminMatchResponse,
    AdminStatusResetRequest,
    AdminStatusResetResponse,
    AdminResolveRequest,
    AdminResolveResponse,
    AdminSnapshotResponse,
    AdminsResponse,
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
    OwnerSetMMRRequest,
    OwnerSetMMRResponse,
    OwnerToggleAdminRequest,
    OwnerToggleAdminResponse,
    PlayersResponse,
    Preferences1v1Response,
    PreferencesUpsertRequest,
    PreferencesUpsertResponse,
    ProfileResponse,
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

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/commands/greet/{discord_uid}", response_model=GreetingResponse)
async def greet(
    discord_uid: int,
    app: Backend = Depends(get_backend),
) -> GreetingResponse:
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
    return AdminBanResponse(success=success, new_is_banned=new_is_banned)


# --- /admin statusreset ---


@router.put("/admin/statusreset", response_model=AdminStatusResetResponse)
async def admin_statusreset(
    request: AdminStatusResetRequest,
    app: Backend = Depends(get_backend),
) -> AdminStatusResetResponse:
    success, error, old_status = app.orchestrator.reset_player_status(
        request.discord_uid
    )
    return AdminStatusResetResponse(success=success, error=error, old_status=old_status)


# --- /admin match ---


@router.get("/admin/matches_1v1/{match_id}", response_model=AdminMatchResponse)
async def admin_match(
    match_id: int,
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
            from backend.lookups.admin_lookups import get_admin_by_discord_uid

            admin = get_admin_by_discord_uid(admin_uid)

    # Get replays for this match.
    from backend.lookups.replay_1v1_lookups import get_replays_1v1_by_match_id

    replays = get_replays_1v1_by_match_id(match_id) or []

    # Run verification on each replay.
    verifications: list[dict | None] = []
    replay_urls: list[str | None] = []
    season_maps = app.state_manager.maps.get("1v1", {}).get("season_alpha", {})

    for replay in replays:
        replay_urls.append(replay.get("replay_path"))
        if match is not None:
            from backend.algorithms.replay_verifier import verify_replay

            verification = verify_replay(
                dict(replay), dict(match), app.state_manager.mods, season_maps
            )
            verifications.append(verification)
        else:
            verifications.append(None)

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
) -> AdminResolveResponse:
    result = app.orchestrator.admin_resolve_match(
        match_id, request.result, request.admin_discord_uid
    )
    if result.get("success"):
        return AdminResolveResponse(success=True, data=result)
    return AdminResolveResponse(
        success=False, error=result.get("error", "Unknown error")
    )


# --- /admin snapshot ---


@router.get("/admin/snapshot_1v1", response_model=AdminSnapshotResponse)
async def admin_snapshot(
    app: Backend = Depends(get_backend),
) -> AdminSnapshotResponse:
    queue = app.orchestrator.get_queue_snapshot_1v1()
    active = app.orchestrator.get_active_matches_1v1()

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

    return AdminSnapshotResponse(
        queue=queue, active_matches=active, dataframe_stats=stats
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
    return OwnerToggleAdminResponse(**result)


# --- /owner mmr ---


@router.put("/owner/mmr", response_model=OwnerSetMMRResponse)
async def owner_set_mmr(
    request: OwnerSetMMRRequest,
    app: Backend = Depends(get_backend),
) -> OwnerSetMMRResponse:
    success, old_mmr = app.orchestrator.admin_set_mmr(
        request.discord_uid, request.race, request.new_mmr
    )
    return OwnerSetMMRResponse(success=success, old_mmr=old_mmr)


# --- /help ---

# --- /leaderboard ---

# --- /profile ---


@router.get("/profile/{discord_uid}", response_model=ProfileResponse)
async def profile(
    discord_uid: int,
    app: Backend = Depends(get_backend),
) -> ProfileResponse:
    player, mmrs = app.orchestrator.get_profile(discord_uid)
    return ProfileResponse(player=player, mmrs_1v1=mmrs)


# --- /prune ---

# --- /queue ---


@router.post("/queue_1v1/join", response_model=QueueJoinResponse)
async def queue_join(
    request: QueueJoinRequest,
    app: Backend = Depends(get_backend),
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
    return QueueJoinResponse(success=success, message=message)


@router.delete("/queue_1v1/leave", response_model=QueueLeaveResponse)
async def queue_leave(
    request: QueueLeaveRequest,
    app: Backend = Depends(get_backend),
) -> QueueLeaveResponse:
    success, message = app.orchestrator.leave_queue_1v1(request.discord_uid)
    return QueueLeaveResponse(success=success, message=message)


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
) -> MatchConfirmResponse:
    success, both_confirmed = app.orchestrator.confirm_match(
        match_id, request.discord_uid
    )
    if success and both_confirmed:
        # Both players confirmed — broadcast so bot can send match details.
        from backend.api.app import ws_manager

        match = app.orchestrator.get_match_1v1(match_id)
        if match is not None:
            await ws_manager.broadcast("both_confirmed", dict(match))
    return MatchConfirmResponse(success=success, both_confirmed=both_confirmed)


@router.put("/matches_1v1/{match_id}/abort", response_model=MatchAbortResponse)
async def match_abort(
    match_id: int,
    request: MatchAbortRequest,
    app: Backend = Depends(get_backend),
) -> MatchAbortResponse:
    success, message = app.orchestrator.abort_match(match_id, request.discord_uid)
    if success:
        from backend.api.app import ws_manager

        match = app.orchestrator.get_match_1v1(match_id)
        if match is not None:
            await ws_manager.broadcast("match_aborted", dict(match))
    return MatchAbortResponse(success=success, message=message)


@router.put("/matches_1v1/{match_id}/report", response_model=MatchReportResponse)
async def match_report(
    match_id: int,
    request: MatchReportRequest,
    app: Backend = Depends(get_backend),
) -> MatchReportResponse:
    success, message, match = app.orchestrator.report_match_result(
        match_id, request.discord_uid, request.report
    )
    if success and match is not None:
        from backend.api.app import ws_manager

        result = match.get("match_result")
        if result == "conflict":
            await ws_manager.broadcast("match_conflict", dict(match))
        elif result is not None:
            await ws_manager.broadcast("match_completed", dict(match))
    return MatchReportResponse(success=success, message=message, match=match)


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
    return SetCountryConfirmResponse(success=success, message=message)


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
    return SetupConfirmResponse(success=success, message=message)


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
    return TermsOfServiceConfirmResponse(success=success, message=message)


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
        return ReplayUploadResponse(success=False, error="Match not found.")

    p1_uid = match["player_1_discord_uid"]
    p2_uid = match["player_2_discord_uid"]
    if discord_uid not in (p1_uid, p2_uid):
        return ReplayUploadResponse(
            success=False, error="You are not a participant in this match."
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
        return ReplayUploadResponse(
            success=False, error=f"Replay parse executor failed: {exc}"
        )

    if parsed.get("error"):
        return ReplayUploadResponse(success=False, error=parsed["error"])

    # --- 3. Build paths and insert pending row ---
    uploaded_at = datetime.now(timezone.utc)
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
    final_path: str = public_url if upload_status == "completed" else storage_path  # type: ignore[assignment]
    app.orchestrator.update_replay_status(replay_id, upload_status, final_path)

    # --- 6. Update the match row ---
    app.orchestrator.update_match_replay_refs(
        match_id, player_num, final_path, replay_id, uploaded_at
    )

    # --- 7. Verify and return ---
    season_maps = app.state_manager.maps.get("1v1", {}).get("season_alpha", {})
    verification = verify_replay(
        parsed, dict(match), app.state_manager.mods, season_maps
    )

    return ReplayUploadResponse(
        success=True,
        parsed=parsed,
        verification=verification,
        replay_id=replay_id,
        upload_status=upload_status,
    )
