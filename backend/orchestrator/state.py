import polars as pl
import structlog

from backend.database.database import DatabaseReader
from backend.domain_types.ephemeral import LeaderboardEntry1v1, QueueEntry1v1

from common.json_types import (
    Country,
    CrossTableData,
    Emote,
    GameModeData,
    Mod,
    Race,
    RegionData,
)

from common.loader import JSONLoader


class StateManager:
    def __init__(self) -> None:
        # Static data from JSON files for lookups
        self.countries: dict[str, Country] = {}
        self.cross_table: CrossTableData = {
            "region_order": [],
            "mappings": {},
            "pings": {},
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
        # Note: "events" is intentionally absent — it is write-only at runtime.
        self.admins_df: pl.DataFrame = pl.DataFrame()
        self.players_df: pl.DataFrame = pl.DataFrame()
        self.notifications_df: pl.DataFrame = pl.DataFrame()
        self.matches_1v1_df: pl.DataFrame = pl.DataFrame()
        self.mmrs_1v1_df: pl.DataFrame = pl.DataFrame()
        self.preferences_1v1_df: pl.DataFrame = pl.DataFrame()
        self.replays_1v1_df: pl.DataFrame = pl.DataFrame()
        self.matches_2v2_df: pl.DataFrame = pl.DataFrame()
        self.mmrs_2v2_df: pl.DataFrame = pl.DataFrame()
        self.preferences_2v2_df: pl.DataFrame = pl.DataFrame()
        self.replays_2v2_df: pl.DataFrame = pl.DataFrame()

        # Current application state
        self.leaderboard_1v1: list[LeaderboardEntry1v1] = []
        # self.leaderboard_2v2: list[LeaderboardEntry2v2] = []
        # self.leaderboard_FFA: list[LeaderboardEntryFFA] = []
        self.queue_1v1: list[QueueEntry1v1] = []
        # self.queue_2v2: list[QueueEntry2v2] = []
        # self.queue_FFA: list[QueueEntryFFA] = []
        # self.timed_out_players: list[int] = []

        self._populate_json_data()
        self._populate_postgres_data()
        self._populate_leaderboard()

    def _populate_json_data(self) -> None:
        json_data = JSONLoader().load_core_data()

        for key, value in json_data.items():
            if not hasattr(self, key):
                raise ValueError(f"StateManager does not have attribute {key}")
            setattr(self, key, value)

    def _populate_postgres_data(self) -> None:
        db_data = DatabaseReader().load_all_tables()

        for table_name, df in db_data.items():
            if not hasattr(self, f"{table_name}_df"):
                raise ValueError(
                    f"StateManager does not have attribute {table_name}_df"
                )
            setattr(self, f"{table_name}_df", df)

    def _populate_leaderboard(self) -> None:
        from backend.algorithms.leaderboard import build_leaderboard_1v1

        logger = structlog.get_logger(__name__)
        self.leaderboard_1v1 = build_leaderboard_1v1(self.mmrs_1v1_df, self.players_df)
        logger.info(
            f"Leaderboard populated at startup: {len(self.leaderboard_1v1)} entries"
        )
