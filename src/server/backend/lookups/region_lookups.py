from server.backend.orchestrator.state import StateManager
from server.backend.types.json_types import GeographicRegion, GameServer, GameRegion

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------


def _get_state_manager() -> StateManager:
    if _state_manager is None:
        raise RuntimeError(_MODULE_NOT_INITIALIZED)
    return _state_manager


# ----------
# Public API
# ----------


def init_region_lookups(state_manager: StateManager) -> None:
    global _state_manager
    _state_manager = state_manager


# --- Geographic Regions ---


def get_geographic_regions() -> dict[str, GeographicRegion]:
    return _get_state_manager().regions["geographic_regions"]


def get_geographic_region_by_code(code: str) -> GeographicRegion | None:
    return get_geographic_regions().get(code)


def get_geographic_region_by_name(name: str) -> GeographicRegion | None:
    return next(
        (
            region
            for region in get_geographic_regions().values()
            if region["name"] == name
        ),
        None,
    )


def get_geographic_region_by_globe_emote_code(
    globe_emote_code: str,
) -> GeographicRegion | None:
    return next(
        (
            region
            for region in get_geographic_regions().values()
            if region["globe_emote_code"] == globe_emote_code
        ),
        None,
    )


# --- Game Servers ---


def get_game_servers() -> dict[str, GameServer]:
    return _get_state_manager().regions["game_servers"]


def get_game_server_by_code(code: str) -> GameServer | None:
    return get_game_servers().get(code)


def get_game_server_by_name(name: str) -> GameServer | None:
    return next(
        (server for server in get_game_servers().values() if server["name"] == name),
        None,
    )


def get_game_server_by_short_name(short_name: str) -> GameServer | None:
    return next(
        (
            server
            for server in get_game_servers().values()
            if server["short_name"] == short_name
        ),
        None,
    )


def get_game_server_by_game_region_code(game_region_code: str) -> GameServer | None:
    return next(
        (
            server
            for server in get_game_servers().values()
            if server["game_region_code"] == game_region_code
        ),
        None,
    )


# --- Game Regions ---


def get_game_regions() -> dict[str, GameRegion]:
    return _get_state_manager().regions["game_regions"]


def get_game_region_by_code(code: str) -> GameRegion | None:
    return get_game_regions().get(code)


def get_game_region_by_name(name: str) -> GameRegion | None:
    return next(
        (region for region in get_game_regions().values() if region["name"] == name),
        None,
    )
