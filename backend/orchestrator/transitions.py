from datetime import datetime, timezone

import polars as pl
import structlog

from backend.database.database import DatabaseWriter
from backend.orchestrator.state import StateManager

from common.lookups.country_lookups import get_country_by_name


logger = structlog.get_logger(__name__)


class TransitionManager:
    def __init__(self, state_manager: StateManager, db_writer: DatabaseWriter) -> None:
        self._state_manager = state_manager
        self._db_writer = db_writer

    def _handle_missing_player(self, discord_uid: int, discord_username: str) -> dict:
        """Return the player row, creating it in the DB and cache if it doesn't exist."""
        df = self._state_manager.players_df

        rows = df.filter(pl.col("discord_uid") == discord_uid)
        if not rows.is_empty():
            logger.info(
                f"Player {discord_username} with ID {discord_uid} already exists"
            )
            return rows.row(0, named=True)

        logger.info(
            f"Creating new player row for {discord_username} with ID {discord_uid}"
        )
        created = self._db_writer.add_player(discord_uid, discord_username)
        self._state_manager.players_df = df.vstack(
            pl.DataFrame([created]).cast(df.schema)
        )
        logger.info(
            f"Successfully created new player row for {discord_username} with ID {discord_uid}"
        )
        return created

    def set_country_for_player(
        self, discord_uid: int, discord_username: str, country_name: str
    ) -> tuple[bool, str | None]:
        player = self._handle_missing_player(discord_uid, discord_username)

        country = get_country_by_name(country_name)
        if country is None:
            return False, f"Country {country_name} not found."
        country_code = country["code"]

        player_id: int = player["id"]
        df: pl.DataFrame = self._state_manager.players_df
        self._db_writer.update_player_nationality(player_id, country_code)

        self._state_manager.players_df = df.with_columns(
            nationality=pl.when(pl.col("id") == player_id)
            .then(pl.lit(country_code))
            .otherwise(pl.col("nationality"))
        )

        logger.info(
            f"Successfully set country for player {discord_username}"
            f"to {country_name} ({country_code})"
        )
        return True, f"Country successfully set to {country_name}."

    def setup_player(
        self,
        discord_uid: int,
        discord_username: str,
        player_name: str,
        alt_player_names: list[str] | None,
        battletag: str,
        nationality_code: str,
        location_code: str,
        language_code: str,
    ) -> tuple[bool, str | None]:
        player = self._handle_missing_player(discord_uid, discord_username)
        player_id: int = player["id"]
        completed_setup_at = datetime.now(timezone.utc)

        self._db_writer.upsert_player_setup(
            player_id=player_id,
            discord_username=discord_username,
            player_name=player_name,
            alt_player_names=alt_player_names,
            battletag=battletag,
            nationality_code=nationality_code,
            location_code=location_code,
            language_code=language_code,
            completed_setup_at=completed_setup_at,
        )

        df = self._state_manager.players_df
        updated = df.filter(pl.col("id") == player_id).to_dicts()[0]
        updated.update(
            {
                "discord_username": discord_username,
                "player_name": player_name,
                "alt_player_names": alt_player_names,
                "battletag": battletag,
                "nationality": nationality_code,
                "location": location_code,
                "language": language_code,
                "completed_setup": True,
                "completed_setup_at": completed_setup_at,
            }
        )
        self._state_manager.players_df = df.filter(pl.col("id") != player_id).vstack(
            pl.DataFrame([updated]).cast(df.schema)
        )

        logger.info(
            f"Successfully completed setup for player {discord_username} ({discord_uid})"
        )
        return True, f"Setup complete for {player_name}."
