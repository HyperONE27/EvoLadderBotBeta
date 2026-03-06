import polars as pl
from typing import cast

from backend.orchestrator.state import StateManager


class TransitionManager:
    def __init__(self, state_manager: StateManager) -> None:
        self._state_manager = state_manager

    def _handle_missing_player(self, discord_uid: int, discord_username: str) -> None:
        df = self._state_manager.players_df

        # Check if row for player already exists
        rows = df.filter(pl.col("discord_uid") == discord_uid)
        if not rows.is_empty():
            # Player already exists, do nothing
            return

        # Player does not exist, create their row
        new_row_id = (cast(int, df["id"].max()) + 1) if not df.is_empty() else 1
        new_row_df = pl.DataFrame(
            [
                {
                    "id": new_row_id,
                    "discord_uid": discord_uid,
                    "discord_username": discord_username,
                    "player_name": None,
                    "alt_player_names": None,
                    "battletag": None,
                    "nationality": None,
                    "location": None,
                    "is_banned": False,
                    "accepted_tos": False,
                    "accepted_tos_at": None,
                    "completed_setup": False,
                    "completed_setup_at": None,
                    "player_status": "idle",
                    "current_match_mode": None,
                    "current_match_id": None,
                }
            ]
        ).cast(df.schema)

        self._state_manager.players_df = df.vstack(new_row_df)
        return

    def set_country_for_player(
        self, discord_uid: int, discord_username: str, country_name: str
    ) -> tuple[bool, str | None]:
        self._handle_missing_player(discord_uid, discord_username)

        df = self._state_manager.players_df
        self._state_manager.players_df = df.with_columns(
            nationality=pl.when(pl.col("discord_uid") == discord_uid)
            .then(pl.lit(country_name))
            .otherwise(pl.col("nationality"))
        )
        return True, None
