"""Resolve a player by ladder name, Discord username, or Discord ID."""

from typing import Any

import structlog

from bot.core.config import BACKEND_URL
from bot.core.http import get_session

logger = structlog.get_logger(__name__)


async def resolve_player_by_string(player: str) -> dict[str, Any] | None:
    """Fetch a player row by ladder name, Discord username, or Discord ID string.

    Returns the player dict on success, or None if not found or the backend is
    unreachable.
    """
    try:
        async with get_session().get(f"{BACKEND_URL}/players/by_name/{player}") as resp:
            if resp.status == 404:
                return None
            data = await resp.json()
    except Exception:
        logger.warning("resolve_player_by_string: backend unreachable", player=player)
        return None

    return data.get("player") or None
