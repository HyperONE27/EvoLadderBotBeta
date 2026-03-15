from fastapi import APIRouter, Depends

from backend.api.dependencies import get_backend
from backend.api.models import (
    GreetingResponse,
    Matches1v1Response,
    MMRs1v1Response,
    PlayersResponse,
    SetCountryConfirmRequest,
    SetCountryConfirmResponse,
    SetupConfirmRequest,
    SetupConfirmResponse,
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

# --- /prune ---

# --- /queue ---

# --- /setcountry ---


@router.put("/commands/setcountry")
async def setcountry(
    request: SetCountryConfirmRequest,
    app: Backend = Depends(get_backend),
) -> SetCountryConfirmResponse:
    success, message = app.orchestrator.setcountry(
        request.discord_uid,
        request.discord_username,
        request.country_name,
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


@router.get("/mmrs_1v1/{discord_uid}/{race}", response_model=MMRs1v1Response)
async def mmrs_1v1(
    discord_uid: int,
    race: str,
    app: Backend = Depends(get_backend),
) -> MMRs1v1Response:
    return MMRs1v1Response(mmr=app.orchestrator.get_mmr_1v1(discord_uid, race))
