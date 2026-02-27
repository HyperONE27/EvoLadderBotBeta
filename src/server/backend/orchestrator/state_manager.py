import polars as pl

from server.backend.config import Admin
from server.backend.types.json_types import (
    Country,
    CrossTableData,
    Emote,
    GameModeData,
    Mod,
    Race,
    RegionData,
)
from server.backend.types.state_types import QueueEntry1v1


class StateManager:
    def __init__(self) -> None:
        # Admins
        self.admins: list[Admin] = []

        # Static data from JSON files for lookups
        self.countries: dict[str, Country] = {}
        self.cross_table: CrossTableData = {"region_order": [], "mappings": {}}
        self.emotes: dict[str, Emote] = {}
        self.maps: dict[str, GameModeData] = {}
        self.mods: dict[str, Mod] = {}
        self.races: dict[str, Race] = {}
        self.regions: RegionData = {
            "geographic_regions": {},
            "game_servers": {},
            "game_regions": {},
        }

        # In-memory DataFrames (cacshouhing the entire database).
        # None until populate_state_manager() has been called by DataLoader.
        self.players_df: pl.DataFrame | None = None
        self.notifications_df: pl.DataFrame | None = None
        self.events_df: pl.DataFrame | None = None
        self.matches_1v1_df: pl.DataFrame | None = None
        self.mmrs_1v1_df: pl.DataFrame | None = None
        self.preferences_1v1_df: pl.DataFrame | None = None
        self.replays_1v1_df: pl.DataFrame | None = None

        # Current application state
        self.queue_1v1: list[QueueEntry1v1] = []
        # self.write_back_queue = []
