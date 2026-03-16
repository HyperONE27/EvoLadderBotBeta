from fastapi import APIRouter, Depends

from backend.api.dependencies import get_backend
from backend.api.models import (
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
    SetCountryConfirmRequest,
    SetCountryConfirmResponse,
    SetupConfirmRequest,
    SetupConfirmResponse,
    TermsOfServiceConfirmRequest,
    TermsOfServiceConfirmResponse,
)
from backend.core.bootstrap import Backend

router = APIRouter()


@router.get("/commands/greet/{discord_uid}", response_model=GreetingResponse)
async def greet(
    discord_uid: int,
    app: Backend = Depends(get_backend),
) -> GreetingResponse:
    return GreetingResponse(message=f"👋 Hello, {discord_uid}!")


# --- /owner admin ---

# --- /owner mmr ---

# --- /owner profile ---

# --- /admin ban ---

# --- /admin match ---

# --- /admin profile ---

# --- /admin resolve ---

# --- /admin snapshot ---

# --- /admin status ---

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
        if result == "invalidated":
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
