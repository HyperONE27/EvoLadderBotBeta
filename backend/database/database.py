from datetime import datetime

import polars as pl
from supabase import create_client, Client
from typing import Any, cast

from backend.core.config import DATABASE
from backend.domain_types.dataframes import TABLE_SCHEMAS


# Connection functions
def _create_read_client() -> Client:
    return create_client(DATABASE["url"], DATABASE["anon_key"])


def _create_write_client() -> Client:
    return create_client(DATABASE["url"], DATABASE["service_role_key"])


class DatabaseReader:
    def __init__(self) -> None:
        self.client: Client = _create_read_client()

    def load_all_tables(self) -> dict[str, pl.DataFrame]:
        """Load all database tables into Polars DataFrames."""
        tables: dict[str, pl.DataFrame] = {}

        for table_name in TABLE_SCHEMAS.keys():
            tables[table_name] = self._load_table(table_name)

        return tables

    def _get_table_schema(self, table_name: str) -> dict[str, pl.DataType]:
        """Get the Polars schema for a table."""
        schema = TABLE_SCHEMAS.get(table_name)
        if schema is None:
            raise ValueError(f"No schema defined for table '{table_name}'")
        return schema

    def _load_table(self, table_name: str) -> pl.DataFrame:
        """Load a single table with strict schema validation."""
        try:
            response = self.client.table(table_name).select("*").execute()
            data = response.data
        except Exception as e:
            raise RuntimeError(f"Failed to query table '{table_name}': {e}")

        schema = self._get_table_schema(table_name)

        if not data:
            # Return a correctly-typed empty DataFrame so downstream code
            # can rely on the schema even when the table has no rows yet.
            return pl.DataFrame(schema=schema)

        return self._validate_schema(
            pl.DataFrame(data, infer_schema_length=None),
            schema,
            table_name,
        )

    def _validate_schema(
        self,
        df: pl.DataFrame,
        expected_schema: dict[str, pl.DataType],
        table_name: str,
    ) -> pl.DataFrame:
        """Validate DataFrame matches expected schema and return the cast DataFrame."""

        expected_columns = set(expected_schema.keys())
        actual_columns = set(df.columns)

        missing_columns = expected_columns - actual_columns
        extra_columns = actual_columns - expected_columns

        if missing_columns:
            raise ValueError(
                f"Table '{table_name}' missing expected columns: {missing_columns}"
            )

        if extra_columns:
            raise ValueError(
                f"Table '{table_name}' has unexpected columns: {extra_columns}"
            )

        try:
            return df.cast(pl.Schema(expected_schema))
        except Exception as e:
            raise ValueError(f"Table '{table_name}' schema validation failed: {e}")


class DatabaseWriter:
    def __init__(self) -> None:
        self.client: Client = _create_write_client()

    def add_player(self, discord_uid: int, discord_username: str) -> dict:
        """Insert a new player row and return the created row (with DB-assigned id)."""
        data: dict[str, Any] = {
            "discord_uid": discord_uid,
            "discord_username": discord_username,
            "player_name": None,
            "alt_player_names": None,
            "battletag": None,
            "nationality": None,
            "location": None,
            "language": "enUS",
            "is_banned": False,
            "accepted_tos": False,
            "accepted_tos_at": None,
            "completed_setup": False,
            "completed_setup_at": None,
            "player_status": "idle",
            "current_match_mode": None,
            "current_match_id": None,
        }
        response = self.client.table("players").insert(data).execute()
        return cast(dict[str, Any], response.data[0])

    def update_player_nationality(self, player_id: int, country_code: str) -> None:
        """Update the nationality field for a player row."""
        self.client.table("players").update({"nationality": country_code}).eq(
            "id", player_id
        ).execute()

    def upsert_player_setup(
        self,
        player_id: int,
        discord_username: str,
        player_name: str,
        alt_player_names: list[str] | None,
        battletag: str,
        nationality_code: str,
        location_code: str,
        language_code: str,
        completed_setup_at: datetime,
    ) -> None:
        """Write all setup fields for a player and mark setup as complete."""
        self.client.table("players").update(
            {
                "discord_username": discord_username,
                "player_name": player_name,
                "alt_player_names": alt_player_names,
                "battletag": battletag,
                "nationality": nationality_code,
                "location": location_code,
                "language": language_code,
                "completed_setup": True,
                "completed_setup_at": completed_setup_at.isoformat(),
            }
        ).eq("id", player_id).execute()

    def upsert_player_tos(
        self,
        player_id: int,
        accepted: bool,
        accepted_tos_at: datetime,
    ) -> None:
        """Write the TOS acceptance decision and timestamp for a player row."""
        self.client.table("players").update(
            {
                "accepted_tos": accepted,
                "accepted_tos_at": accepted_tos_at.isoformat(),
            }
        ).eq("id", player_id).execute()

    # ------------------------------------------------------------------
    # Player status
    # ------------------------------------------------------------------

    def update_player_status(
        self,
        player_id: int,
        player_status: str,
        current_match_mode: str | None,
        current_match_id: int | None,
    ) -> None:
        """Update player_status, current_match_mode, and current_match_id."""
        self.client.table("players").update(
            {
                "player_status": player_status,
                "current_match_mode": current_match_mode,
                "current_match_id": current_match_id,
            }
        ).eq("id", player_id).execute()

    # ------------------------------------------------------------------
    # MMR 1v1
    # ------------------------------------------------------------------

    def add_mmr_1v1(
        self,
        discord_uid: int,
        player_name: str,
        race: str,
        mmr: int,
    ) -> dict:
        """Insert a new MMR row with default stats and return the created row."""
        data: dict[str, Any] = {
            "discord_uid": discord_uid,
            "player_name": player_name,
            "race": race,
            "mmr": mmr,
            "games_played": 0,
            "games_won": 0,
            "games_lost": 0,
            "games_drawn": 0,
        }
        response = self.client.table("mmrs_1v1").insert(data).execute()
        return cast(dict[str, Any], response.data[0])

    def update_mmr_1v1(
        self,
        discord_uid: int,
        race: str,
        *,
        mmr: int,
        games_played: int,
        games_won: int,
        games_lost: int,
        games_drawn: int,
        last_played_at: datetime,
    ) -> None:
        """Update an existing MMR row after a match completes."""
        self.client.table("mmrs_1v1").update(
            {
                "mmr": mmr,
                "games_played": games_played,
                "games_won": games_won,
                "games_lost": games_lost,
                "games_drawn": games_drawn,
                "last_played_at": last_played_at.isoformat(),
            }
        ).eq("discord_uid", discord_uid).eq("race", race).execute()

    # ------------------------------------------------------------------
    # Matches 1v1
    # ------------------------------------------------------------------

    def add_match_1v1(
        self,
        player_1_discord_uid: int,
        player_2_discord_uid: int,
        player_1_name: str,
        player_2_name: str,
        player_1_race: str,
        player_2_race: str,
        player_1_mmr: int,
        player_2_mmr: int,
        map_name: str,
        server_name: str,
        assigned_at: datetime,
    ) -> dict:
        """Insert a new match row and return the created row (with DB-assigned id)."""
        data: dict[str, Any] = {
            "player_1_discord_uid": player_1_discord_uid,
            "player_2_discord_uid": player_2_discord_uid,
            "player_1_name": player_1_name,
            "player_2_name": player_2_name,
            "player_1_race": player_1_race,
            "player_2_race": player_2_race,
            "player_1_mmr": player_1_mmr,
            "player_2_mmr": player_2_mmr,
            "map_name": map_name,
            "server_name": server_name,
            "assigned_at": assigned_at.isoformat(),
        }
        response = self.client.table("matches_1v1").insert(data).execute()
        return cast(dict[str, Any], response.data[0])

    def update_match_1v1_report(
        self,
        match_id: int,
        *,
        player_1_report: str | None = None,
        player_2_report: str | None = None,
    ) -> None:
        """Set one or both report columns on a match row."""
        updates: dict[str, Any] = {}
        if player_1_report is not None:
            updates["player_1_report"] = player_1_report
        if player_2_report is not None:
            updates["player_2_report"] = player_2_report
        if updates:
            self.client.table("matches_1v1").update(updates).eq(
                "id", match_id
            ).execute()

    # ------------------------------------------------------------------
    # Preferences 1v1
    # ------------------------------------------------------------------

    def upsert_preferences_1v1(
        self,
        discord_uid: int,
        last_chosen_races: list[str],
        last_chosen_vetoes: list[str],
    ) -> dict:
        """Upsert a player's 1v1 queue preferences."""
        data: dict[str, Any] = {
            "discord_uid": discord_uid,
            "last_chosen_races": last_chosen_races,
            "last_chosen_vetoes": last_chosen_vetoes,
        }
        response = (
            self.client.table("preferences_1v1")
            .upsert(data, on_conflict="discord_uid")
            .execute()
        )
        return cast(dict[str, Any], response.data[0])

    # ------------------------------------------------------------------
    # Player status (bulk)
    # ------------------------------------------------------------------

    def reset_all_player_statuses(self) -> None:
        """Reset all players to idle status with no active match."""
        self.client.table("players").update(
            {
                "player_status": "idle",
                "current_match_mode": None,
                "current_match_id": None,
            }
        ).neq("player_status", "idle").execute()

    # ------------------------------------------------------------------
    # Matches 1v1 (continued)
    # ------------------------------------------------------------------

    def update_match_1v1_result(
        self,
        match_id: int,
        *,
        match_result: str,
        player_1_mmr_change: int | None = None,
        player_2_mmr_change: int | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        """Finalise a match with the resolved result and optional MMR deltas."""
        updates: dict[str, Any] = {"match_result": match_result}
        if player_1_mmr_change is not None:
            updates["player_1_mmr_change"] = player_1_mmr_change
        if player_2_mmr_change is not None:
            updates["player_2_mmr_change"] = player_2_mmr_change
        if completed_at is not None:
            updates["completed_at"] = completed_at.isoformat()
        self.client.table("matches_1v1").update(updates).eq("id", match_id).execute()

    def finalise_match_1v1(
        self,
        match_id: int,
        *,
        match_result: str,
        player_1_report: str | None = None,
        player_2_report: str | None = None,
        player_1_mmr_change: int | None = None,
        player_2_mmr_change: int | None = None,
        completed_at: datetime,
    ) -> None:
        """Write all terminal match fields in a single UPDATE."""
        updates: dict[str, Any] = {
            "match_result": match_result,
            "completed_at": completed_at.isoformat(),
        }
        if player_1_report is not None:
            updates["player_1_report"] = player_1_report
        if player_2_report is not None:
            updates["player_2_report"] = player_2_report
        if player_1_mmr_change is not None:
            updates["player_1_mmr_change"] = player_1_mmr_change
        if player_2_mmr_change is not None:
            updates["player_2_mmr_change"] = player_2_mmr_change
        self.client.table("matches_1v1").update(updates).eq("id", match_id).execute()

    # ------------------------------------------------------------------
    # Replays 1v1
    # ------------------------------------------------------------------

    def add_replay_1v1(self, data: dict[str, Any]) -> dict:
        """Insert a new replay row and return the created row (with DB-assigned id)."""
        response = self.client.table("replays_1v1").insert(data).execute()
        return cast(dict[str, Any], response.data[0])

    def update_replay_1v1_status(
        self,
        replay_id: int,
        status: str,
        replay_path: str | None = None,
    ) -> None:
        """Update upload_status and optionally replay_path for a replay row."""
        updates: dict[str, Any] = {"upload_status": status}
        if replay_path is not None:
            updates["replay_path"] = replay_path
        self.client.table("replays_1v1").update(updates).eq("id", replay_id).execute()

    def update_match_1v1_replay(
        self,
        match_id: int,
        player_num: int,
        replay_path: str,
        replay_row_id: int,
        uploaded_at: datetime,
    ) -> None:
        """Update a match row with the latest replay path, row ID, and timestamp."""
        updates: dict[str, Any] = {
            f"player_{player_num}_replay_path": replay_path,
            f"player_{player_num}_replay_row_id": replay_row_id,
            f"player_{player_num}_uploaded_at": uploaded_at.isoformat(),
        }
        self.client.table("matches_1v1").update(updates).eq("id", match_id).execute()

    # ------------------------------------------------------------------
    # Players (admin operations)
    # ------------------------------------------------------------------

    def update_player_ban_status(self, player_id: int, is_banned: bool) -> None:
        """Toggle the is_banned flag for a player."""
        self.client.table("players").update({"is_banned": is_banned}).eq(
            "id", player_id
        ).execute()

    # ------------------------------------------------------------------
    # Matches 1v1 (admin operations)
    # ------------------------------------------------------------------

    def admin_resolve_match_1v1(
        self,
        match_id: int,
        *,
        match_result: str,
        player_1_mmr_change: int,
        player_2_mmr_change: int,
        admin_discord_uid: int,
        completed_at: datetime,
    ) -> None:
        """Admin-resolve a match: set result, MMR deltas, and admin audit columns."""
        self.client.table("matches_1v1").update(
            {
                "match_result": match_result,
                "player_1_mmr_change": player_1_mmr_change,
                "player_2_mmr_change": player_2_mmr_change,
                "admin_intervened": True,
                "admin_discord_uid": admin_discord_uid,
                "completed_at": completed_at.isoformat(),
            }
        ).eq("id", match_id).execute()

    # ------------------------------------------------------------------
    # MMR 1v1 (admin operations)
    # ------------------------------------------------------------------

    def update_mmr_1v1_game_stats(
        self,
        discord_uid: int,
        race: str,
        *,
        games_played: int,
        games_won: int,
        games_lost: int,
        games_drawn: int,
    ) -> None:
        """Update only game stat columns on an MMR row (no MMR change)."""
        self.client.table("mmrs_1v1").update(
            {
                "games_played": games_played,
                "games_won": games_won,
                "games_lost": games_lost,
                "games_drawn": games_drawn,
            }
        ).eq("discord_uid", discord_uid).eq("race", race).execute()

    def set_mmr_1v1_value(self, discord_uid: int, race: str, mmr: int) -> None:
        """Idempotent SET of a player's MMR value. Does not touch game stats."""
        self.client.table("mmrs_1v1").update({"mmr": mmr}).eq(
            "discord_uid", discord_uid
        ).eq("race", race).execute()

    # ------------------------------------------------------------------
    # Admins
    # ------------------------------------------------------------------

    def upsert_admin(
        self,
        discord_uid: int,
        discord_username: str,
        role: str,
        first_promoted_at: datetime,
        last_promoted_at: datetime,
        last_demoted_at: datetime | None = None,
    ) -> dict:
        """Insert or update an admin row. Returns the resulting row."""
        data: dict[str, Any] = {
            "discord_uid": discord_uid,
            "discord_username": discord_username,
            "role": role,
            "first_promoted_at": first_promoted_at.isoformat(),
            "last_promoted_at": last_promoted_at.isoformat(),
            "last_demoted_at": last_demoted_at.isoformat() if last_demoted_at else None,
        }
        response = (
            self.client.table("admins")
            .upsert(data, on_conflict="discord_uid")
            .execute()
        )
        return cast(dict[str, Any], response.data[0])

    def update_admin_role(
        self,
        discord_uid: int,
        role: str,
        last_promoted_at: datetime | None = None,
        last_demoted_at: datetime | None = None,
    ) -> None:
        """Update an admin's role and relevant timestamp."""
        updates: dict[str, Any] = {"role": role}
        if last_promoted_at is not None:
            updates["last_promoted_at"] = last_promoted_at.isoformat()
        if last_demoted_at is not None:
            updates["last_demoted_at"] = last_demoted_at.isoformat()
        self.client.table("admins").update(updates).eq(
            "discord_uid", discord_uid
        ).execute()

    # ------------------------------------------------------------------
    # MMR 1v1 (batch)
    # ------------------------------------------------------------------

    def batch_update_mmrs_1v1(self, rows: list[dict[str, Any]]) -> None:
        """Upsert multiple MMR rows in a single round-trip.

        Each dict must include ``discord_uid``, ``race``, and all other
        non-null columns so the INSERT branch of the upsert cannot fail.
        ``last_played_at`` may be a ``datetime`` — it is serialised here.
        """
        serialised = [
            {**row, "last_played_at": row["last_played_at"].isoformat()} for row in rows
        ]
        self.client.table("mmrs_1v1").upsert(
            serialised, on_conflict="discord_uid,race"
        ).execute()
