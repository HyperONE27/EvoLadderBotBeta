import polars as pl

from backend.config import Admin
from backend.domain_types.state_types import QueueEntry1v1

from common.json_types import (
    Country,
    CrossTableData,
    Emote,
    GameModeData,
    Mod,
    Race,
    RegionData,
)


class StateManager:
    def __init__(self) -> None:
        # Admins
        self.admins: list[Admin] = []

        # Static data from JSON files for lookups
        self.countries: dict[str, Country] = {}
        self.cross_table: CrossTableData = {
            "region_order": [],
            "mappings": {},
        }
        self.emotes: dict[str, Emote] = {}
        self.maps: dict[str, GameModeData] = {}
        self.mods: dict[str, Mod] = {}
        self.races: dict[str, Race] = {}
        self.regions: RegionData = {
            "geographic_regions": {},
            "game_servers": {},
            "game_regions": {},
        }

        # In-memory DataFrames (caching the entire database)
        self.players_df: pl.DataFrame = pl.DataFrame()
        self.notifications_df: pl.DataFrame = pl.DataFrame()
        self.events_df: pl.DataFrame = pl.DataFrame()
        self.matches_1v1_df: pl.DataFrame = pl.DataFrame()
        self.mmrs_1v1_df: pl.DataFrame = pl.DataFrame()
        self.preferences_1v1_df: pl.DataFrame = pl.DataFrame()
        self.replays_1v1_df: pl.DataFrame = pl.DataFrame()

        # Current application state
        self.queue_1v1: list[QueueEntry1v1] = []
        # self.queue_2v2: list[QueueEntry2v2] = []
        # self.queue_FFA: list[QueueEntryFFA] = []
        # self.timed_out_players: list[int] = []
        # self.write_back_queue = []
