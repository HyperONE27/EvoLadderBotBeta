from server.backend.config import CURRENT_SEASON
from server.backend.orchestrator.state_manager import StateManager
from server.backend.types.json_types import Map

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------

def _check_initialized() -> None:
    if _state_manager is None:
        raise RuntimeError(_MODULE_NOT_INITIALIZED)

# ----------
# Public API
# ----------

def init_map_utils(state_manager: StateManager) -> None:
    global _state_manager
    _state_manager = state_manager

def get_maps(*, game_mode: str | None = None, season: str | None = None) -> dict[str, Map]:
    _check_initialized()
    if game_mode and season:
        return _state_manager.maps[game_mode][season]
    elif game_mode:
        return _state_manager.maps[game_mode]
    elif season:
        return {map_data for map_data in _state_manager.maps.values() if map_data["seasons"][season]}
    else:
        return {map_data for map_data in _state_manager.maps.values()}

def get_map_by_short_name(short_name: str) -> Map | None:
    """Look up a single map by its short name across all seasons."""
    _check_initialized()
    return next((map_data for map_data in get_maps().values() if map_data["short_name"] == short_name), None)

def get_map_by_name(name: str) -> Map | None:
    _check_initialized()
    return next((map_data for map_data in get_maps().values() if map_data["name"] == name), None)

def get_map_by_link(link: str) -> Map | None:
    _check_initialized()
    return next((map_data for map_data in get_maps().values()
        if map_data["am_link"] == link or map_data["eu_link"] == link or map_data["as_link"] == link
    ), None)