from common.json_types import Map
from common.protocols import StaticDataSource

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_source: StaticDataSource | None = None

# ----------------
# Internal helpers
# ----------------


def _get_source() -> StaticDataSource:
    if _source is None:
        raise RuntimeError(_MODULE_NOT_INITIALIZED)
    return _source


def _get_maps() -> dict[str, Map]:
    maps: dict[str, Map] = {}
    for game_mode_data in _get_source().maps.values():
        for season_data in game_mode_data.values():
            for map_name, map_data in season_data.items():
                if map_name.strip():
                    maps[map_name] = map_data
    return maps


def _get_game_mode_maps(game_mode: str) -> dict[str, Map]:
    maps: dict[str, Map] = {}
    for season_data in _get_source().maps[game_mode].values():
        for map_name, map_data in season_data.items():
            if map_name.strip():
                maps[map_name] = map_data
    return maps


def _get_season_maps(season: str) -> dict[str, Map]:
    maps: dict[str, Map] = {}
    for game_mode_data in _get_source().maps.values():
        for season_name, season_data in game_mode_data.items():
            if season_name == season:
                for map_name, map_data in season_data.items():
                    if map_name.strip():
                        maps[map_name] = map_data
    return maps


def _get_game_mode_season_maps(game_mode: str, season: str) -> dict[str, Map]:
    maps: dict[str, Map] = {}
    for map_name, map_data in _get_source().maps[game_mode][season].items():
        if map_name.strip():
            maps[map_name] = map_data
    return maps


# ----------
# Public API
# ----------


def get_maps(
    *, game_mode: str | None = None, season: str | None = None
) -> dict[str, Map]:
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
    return next(
        (
            map_data
            for map_data in _get_maps().values()
            if map_data["short_name"] == short_name
        ),
        None,
    )


def get_map_by_name(name: str) -> Map | None:
    return next(
        (
            map_data
            for map_data in _get_maps().values()
            if map_data["name"].lower() == name.lower()
        ),
        None,
    )


def get_map_by_link(link: str) -> Map | None:
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


# ----------------
# Module lifecycle
# ----------------


def init_map_lookups(source: StaticDataSource) -> None:
    """Initialize the map lookups module."""
    global _source
    _source = source
