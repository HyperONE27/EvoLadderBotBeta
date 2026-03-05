from fastapi import APIRouter, Depends

from backend.api.app import get_application
from backend.api.models import GreetingResponse
from backend.bootstrap import Application

router = APIRouter()


@router.get("/commands/greet/{discord_uid}", response_model=GreetingResponse)
async def greet(
    discord_uid: int,
    app: Application = Depends(get_application),
) -> GreetingResponse:
    return GreetingResponse(message=f"Hello, {discord_uid}!")


# /owner admin

# /owner mmr

# /owner profile

# /admin ban

# /admin match

# /admin profile

# /admin resolve

# /admin snapshot

# /admin status

# /help

# /leaderboard

# /profile

# /prune

# /queue

# /setcountry

# /setup

# /termsofservice
