import polars as pl
from typing import Dict, List, Optional

from server.backend.config import Admin
from server.backend.types.game_data import (
    Country, CrossTableData, Emote, Map,
    Mod, Race, RegionData, SeasonData
)


class StateManager:
    _initialised: bool = False
    _instance: Optional["StateManager"] = None

    def __new__(cls) -> "StateManager":
        if cls._instance is not None:
            return cls._instance

        instance = super().__new__(cls)

        # Admins
        instance.admins: List[Admin] = []

        # Basic data for lookups
        instance.countries: Dict[str, Country] = {}
        instance.cross_table: CrossTableData = {
            "region_order": [],
            "mappings": {}
        }
        instance.emotes: Dict[str, Emote] = {}
        instance.maps: Dict[str, SeasonData] = {}
        instance.mods: Dict[str, Mod] = {}
        instance.races: Dict[str, Race] = {}
        instance.regions: RegionData = {
            "geographic_regions": {},
            "game_servers": {},
            "game_regions": {}
        }

        # In-memory DataFrames (caching the entire database).
        # None until populate_state_manager() has been called.
        instance.players_df: Optional[pl.DataFrame] = None
        instance.notifications_df: Optional[pl.DataFrame] = None
        instance.events_df: Optional[pl.DataFrame] = None
        instance.matches_1v1_df: Optional[pl.DataFrame] = None
        instance.mmrs_1v1_df: Optional[pl.DataFrame] = None
        instance.preferences_1v1_df: Optional[pl.DataFrame] = None
        instance.replays_1v1_df: Optional[pl.DataFrame] = None

        cls._instance = instance
        return instance

    def __init__(self) -> None:
        """Singleton initialization is handled in __new__. This method does nothing."""
        pass

