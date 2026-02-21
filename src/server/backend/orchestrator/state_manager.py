import polars as pl
from typing import Dict, List, Optional

from server.backend.config import Admin
from server.backend.types.game_data import (
    Country, CrossTableData, Emote, Map, 
    Mod, Race, RegionData, SeasonData
)

class StateManager:
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Admins
        self.admins: List[Admin] = []

        # Basic data for looksups
        self.countries: Dict[str, Country] = {}
        self.cross_table: CrossTableData = {
            "region_order": [],
            "mappings": {}
        }
        self.emotes: Dict[str, Emote] = {}
        self.maps: Dict[str, SeasonData] = {}
        self.mods: Dict[str, Mod] = {}
        self.races: Dict[str, Race] = {}
        self.regions: RegionData = {
            "geographic_regions": {},
            "game_servers": {},
            "game_regions": {}
        }

        # In-memory DataFrames (caching the entire database)
        self.players_df: Optional[pl.DataFrame] = None
        self.notifications_df: Optional[pl.DataFrame] = None
        self.events_df: Optional[pl.DataFrame] = None  
        self.matches_1v1_df: Optional[pl.DataFrame] = None
        self.mmrs_1v1_df: Optional[pl.DataFrame] = None
        self.preferences_1v1_df: Optional[pl.DataFrame] = None
        self.replays_1v1_df: Optional[pl.DataFrame] = None