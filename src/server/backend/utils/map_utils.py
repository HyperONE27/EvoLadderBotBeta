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


def _get_maps() -> dict[str, Map]:
    _check_initialized()
    maps: dict[str, Map] = {}
    for game_mode_data in _state_manager.maps.values():
        for season_data in game_mode_data.values():
            for map_name, map_data in season_data.items():
                if map_name.strip():
                    maps[map_name] = map_data
    return maps


def _get_game_mode_maps(game_mode: str) -> dict[str, Map]:
    _check_initialized()
    maps: dict[str, Map] = {}
    for season_data in _state_manager.maps[game_mode].values():
        for map_name, map_data in season_data.items():
            if map_name.strip():
                maps[map_name] = map_data
    return maps


def _get_season_maps(season: str) -> dict[str, Map]:
    _check_initialized()
    maps: dict[str, Map] = {}
    for game_mode_data in _state_manager.maps.values():
        for season_name, season_data in game_mode_data.items():
            if season_name == season:
                for map_name, map_data in season_data.items():
                    if map_name.strip():
                        maps[map_name] = map_data
    return maps


def _get_game_mode_season_maps(game_mode: str, season: str) -> dict[str, Map]:
    _check_initialized()
    maps: dict[str, Map] = {}
    for map_name, map_data in _state_manager.maps[game_mode][season].items():
        if map_name.strip():
            maps[map_name] = map_data
    return maps


# ----------
# Public API
# ----------


def init_map_utils(state_manager: StateManager) -> None:
    global _state_manager
    _state_manager = state_manager


def get_maps(
    *, game_mode: (str | None) = None, season: (str | None) = None
) -> dict[str, Map]:
    _check_initialized()
    if game_mode and season:
        return _get_game_mode_season_maps(game_mode, season)
    elif game_mode:
        return _get_game_mode_maps(game_mode)
    elif season:
        return _get_season_maps(season)
    else:
        return _get_maps()


def get_map_by_short_name(short_name: str) -> Map | None:
    """Look up a single map by its short name across all seasons."""
    _check_initialized()
    return next(
        (
            map_data
            for map_data in _get_maps().values()
            if map_data["short_name"] == short_name
        ),
        None,
    )


def get_map_by_name(name: str) -> Map | None:
    _check_initialized()
    return next(
        (map_data for map_data in _get_maps().values() if map_data["name"] == name),
        None,
    )


def get_map_by_link(link: str) -> Map | None:
    _check_initialized()
    return next(
        (
            map_data
            for map_data in _get_maps().values()
            if map_data["am_link"] == link
            or map_data["eu_link"] == link
            or map_data["as_link"] == link
        ),
        None,
    )
