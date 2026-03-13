from typing import Protocol

from common.json_types import (
    Country,
    CrossTableData,
    Emote,
    GameModeData,
    Mod,
    Race,
    RegionData,
)


class StaticDataSource(Protocol):
    """Structural protocol satisfied by both StateManager and Cache.

    Any object exposing these JSON-derived static-data attributes can be used
    to initialize the common lookup modules.
    """

    countries: dict[str, Country]
    cross_table: CrossTableData
    emotes: dict[str, Emote]
    maps: dict[str, GameModeData]
    mods: dict[str, Mod]
    races: dict[str, Race]
    regions: RegionData
