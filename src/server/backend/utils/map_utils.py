from typing import Dict, List
from server.backend.config import CURRENT_SEASON
from server.backend.orchestrator.state_manager import StateManager
from server.backend.types.json_types import Map

ERROR_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------

def _check_initialized() -> None:
    if _state_manager is None:
        raise RuntimeError(ERROR_MODULE_NOT_INITIALIZED)

def _get_all_maps_flat() -> Dict[str, Map]:
    """Return every map across all seasons in a single flat dictionary."""
    _check_initialized()
    result: Dict[str, Map] = {}
    for season_maps in _state_manager.maps.values():
        result.update(season_maps)
    return result

# ----------
# Public API
# ----------

def init_map_utils(state_manager: StateManager) -> None:
    global _state_manager
    _state_manager = state_manager

def get_maps() -> Dict[str, Map]:
    """Return every map across all seasons."""
    _check_initialized()
    return {map_data for map_data in _state_manager.maps.values()}

def get_season_maps(season_code: str = CURRENT_SEASON) -> Dict[str, Map]:
    _check_initialized()
    return _state_manager.maps[season_code]

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