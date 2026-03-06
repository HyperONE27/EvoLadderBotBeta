from fastapi import APIRouter, Depends

from backend.api.dependencies import get_application
from backend.api.models import (
    GreetingResponse,
    SetCountryConfirmRequest,
    SetCountryConfirmResponse,
)
from backend.bootstrap import Application

router = APIRouter()


@router.get("/commands/greet/{discord_uid}", response_model=GreetingResponse)
async def greet(
    discord_uid: int,
    app: Application = Depends(get_application),
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
    app: Application = Depends(get_application),
) -> SetCountryConfirmResponse:
    success, message = app.orchestrator.setcountry(
        request.discord_uid,
        request.discord_username,
        request.country_name,
    )
    return SetCountryConfirmResponse(success=success, message=message)


# --- /setup ---

# --- /termsofservice ---
