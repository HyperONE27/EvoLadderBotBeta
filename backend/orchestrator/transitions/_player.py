"""Player setup, TOS, country, preferences, and startup reset transitions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import structlog

from common.datetime_helpers import utc_now
from common.lookups.country_lookups import get_country_by_code

if TYPE_CHECKING:
    from backend.orchestrator.transitions import TransitionManager

logger = structlog.get_logger(__name__)


def set_country_for_player(
    self: TransitionManager,
    discord_uid: int,
    discord_username: str,
    country_code: str,
) -> tuple[bool, str | None]:
    player = self._handle_missing_player(discord_uid, discord_username)

    country = get_country_by_code(country_code)
    if country is None:
        return False, f"Country code {country_code!r} not found."

    old_nationality = player.get("nationality")
    player_id: int = player["id"]
    df: pl.DataFrame = self._state_manager.players_df
    self._db_writer.update_player_nationality(player_id, country_code)

    self._state_manager.players_df = df.with_columns(
        nationality=pl.when(pl.col("id") == player_id)
        .then(pl.lit(country_code))
        .otherwise(pl.col("nationality"))
    )

    self._db_writer.insert_event(
        {
            "discord_uid": discord_uid,
            "event_type": "player_update",
            "action": "nationality_update",
            "event_data": {
                "field_changes": {
                    "nationality": {"before": old_nationality, "after": country_code}
                },
            },
        }
    )

    logger.info(
        f"Successfully set country for player {discord_username} "
        f"to {country['name']} ({country_code})"
    )
    return True, f"Country successfully set to {country['name']}."


def setup_player(
    self: TransitionManager,
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
    completed_setup_at = utc_now()

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

    self._db_writer.insert_event(
        {
            "discord_uid": discord_uid,
            "event_type": "player_update",
            "action": "profile_update",
            "event_data": {
                "player_name": player_name,
                "alt_player_names": alt_player_names,
                "battletag": battletag,
                "nationality": nationality_code,
                "location": location_code,
                "language": language_code,
                "completed_setup": True,
                "completed_setup_at": completed_setup_at.isoformat(),
            },
        }
    )

    logger.info(
        f"Successfully completed setup for player {discord_username} ({discord_uid})"
    )
    return True, f"Setup complete for {player_name}."


def set_tos_for_player(
    self: TransitionManager,
    discord_uid: int,
    discord_username: str,
    accepted: bool,
) -> tuple[bool, str | None]:
    player = self._handle_missing_player(discord_uid, discord_username)
    player_id: int = player["id"]
    old_accepted_tos: bool = player.get("accepted_tos", False)
    accepted_tos_at = utc_now()

    self._db_writer.upsert_player_tos(player_id, accepted, accepted_tos_at)

    df = self._state_manager.players_df
    updated = df.filter(pl.col("id") == player_id).to_dicts()[0]
    updated.update(
        {
            "accepted_tos": accepted,
            "accepted_tos_at": accepted_tos_at,
        }
    )
    self._state_manager.players_df = df.filter(pl.col("id") != player_id).vstack(
        pl.DataFrame([updated]).cast(df.schema)
    )

    self._db_writer.insert_event(
        {
            "discord_uid": discord_uid,
            "event_type": "player_update",
            "action": "tos_update",
            "event_data": {
                "field_changes": {
                    "accepted_tos": {"before": old_accepted_tos, "after": accepted},
                },
            },
        }
    )

    verb = "accepted" if accepted else "declined"
    logger.info(
        f"Player {discord_username} ({discord_uid}) {verb} the terms of service"
    )
    return True, None


def register_player(
    self: TransitionManager,
    discord_uid: int,
    discord_username: str,
) -> bool:
    """Ensure a player row exists. Returns True if the row was newly created."""
    df = self._state_manager.players_df
    was_created = df.filter(pl.col("discord_uid") == discord_uid).is_empty()
    self._handle_missing_player(discord_uid, discord_username)
    return was_created


def toggle_lobby_guide(self: TransitionManager, discord_uid: int) -> tuple[bool, bool]:
    """Toggle read_lobby_guide for a player. Returns (success, new_value)."""
    df = self._state_manager.players_df
    rows = df.filter(pl.col("discord_uid") == discord_uid)
    if rows.is_empty():
        return False, False

    player = rows.row(0, named=True)
    player_id: int = player["id"]
    new_value = not player["read_lobby_guide"]

    self._db_writer.update_player_lobby_guide(player_id, new_value)

    self._state_manager.players_df = df.with_columns(
        read_lobby_guide=pl.when(pl.col("discord_uid") == discord_uid)
        .then(pl.lit(new_value))
        .otherwise(pl.col("read_lobby_guide"))
    )

    logger.info(f"Player {discord_uid} read_lobby_guide toggled to {new_value}")
    return True, new_value


def reset_all_player_statuses(self: TransitionManager) -> None:
    """Reset all players to idle with no active match (called at startup)."""
    self._db_writer.reset_all_player_statuses()

    df = self._state_manager.players_df
    self._state_manager.players_df = df.with_columns(
        player_status=pl.lit("idle"),
        current_match_mode=pl.lit(None),
        current_match_id=pl.lit(None),
    )
    logger.info("Reset all player statuses to idle")


def upsert_preferences_1v1(
    self: TransitionManager,
    discord_uid: int,
    last_chosen_races: list[str],
    last_chosen_vetoes: list[str],
) -> None:
    """Create or update a player's 1v1 queue preferences."""
    created = self._db_writer.upsert_preferences_1v1(
        discord_uid, last_chosen_races, last_chosen_vetoes
    )

    df = self._state_manager.preferences_1v1_df
    # Remove any existing row for this user, then add the new one.
    self._state_manager.preferences_1v1_df = df.filter(
        pl.col("discord_uid") != discord_uid
    ).vstack(pl.DataFrame([created]).cast(df.schema))

    logger.info(f"Upserted preferences for player {discord_uid}")


def upsert_preferences_2v2(
    self: TransitionManager,
    discord_uid: int,
    last_pure_bw_leader_race: str | None,
    last_pure_bw_member_race: str | None,
    last_mixed_leader_race: str | None,
    last_mixed_member_race: str | None,
    last_pure_sc2_leader_race: str | None,
    last_pure_sc2_member_race: str | None,
    last_chosen_vetoes: list[str],
) -> None:
    """Create or update a player's 2v2 queue preferences."""
    created = self._db_writer.upsert_preferences_2v2(
        discord_uid,
        last_pure_bw_leader_race,
        last_pure_bw_member_race,
        last_mixed_leader_race,
        last_mixed_member_race,
        last_pure_sc2_leader_race,
        last_pure_sc2_member_race,
        last_chosen_vetoes,
    )

    df = self._state_manager.preferences_2v2_df
    self._state_manager.preferences_2v2_df = df.filter(
        pl.col("discord_uid") != discord_uid
    ).vstack(pl.DataFrame([created]).cast(df.schema))

    logger.info(f"Upserted 2v2 preferences for player {discord_uid}")
