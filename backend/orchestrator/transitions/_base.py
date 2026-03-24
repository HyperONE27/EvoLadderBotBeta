"""Shared cache and status helpers used by multiple transition domains."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import structlog

from backend.domain_types.dataframes import Matches1v1Row, row_as

if TYPE_CHECKING:
    from backend.orchestrator.transitions import TransitionManager

logger = structlog.get_logger(__name__)


def _handle_missing_player(
    self: TransitionManager, discord_uid: int, discord_username: str
) -> dict:
    """Return the player row, creating it in the DB and cache if it doesn't exist."""
    df = self._state_manager.players_df

    rows = df.filter(pl.col("discord_uid") == discord_uid)
    if not rows.is_empty():
        # This dumb row is too loud
        # logger.info(f"Player {discord_username} with ID {discord_uid} already exists")
        return rows.row(0, named=True)

    logger.info(f"Creating new player row for {discord_username} with ID {discord_uid}")
    created = self._db_writer.add_player(discord_uid, discord_username)
    self._state_manager.players_df = df.vstack(pl.DataFrame([created]).cast(df.schema))
    from backend.orchestrator.transitions import _notifications as _notifications_mod

    _notifications_mod.ensure_notification_row(self, discord_uid)
    logger.info(
        f"Successfully created new player row for {discord_username} with ID {discord_uid}"
    )
    return created


def _set_player_status(
    self: TransitionManager,
    discord_uid: int,
    status: str,
    match_mode: str | None = None,
    match_id: int | None = None,
) -> None:
    """Update player_status (and match columns) in both cache and DB."""
    df = self._state_manager.players_df
    rows = df.filter(pl.col("discord_uid") == discord_uid)
    if rows.is_empty():
        return

    player_id: int = rows.row(0, named=True)["id"]
    self._db_writer.update_player_status(player_id, status, match_mode, match_id)

    self._state_manager.players_df = df.with_columns(
        player_status=pl.when(pl.col("discord_uid") == discord_uid)
        .then(pl.lit(status))
        .otherwise(pl.col("player_status")),
        current_match_mode=pl.when(pl.col("discord_uid") == discord_uid)
        .then(pl.lit(match_mode))
        .otherwise(pl.col("current_match_mode")),
        current_match_id=pl.when(pl.col("discord_uid") == discord_uid)
        .then(pl.lit(match_id))
        .otherwise(pl.col("current_match_id")),
    )


def _get_match_row(self: TransitionManager, match_id: int) -> Matches1v1Row | None:
    df = self._state_manager.matches_1v1_df
    rows = df.filter(pl.col("id") == match_id)
    if rows.is_empty():
        return None
    return row_as(Matches1v1Row, rows.row(0, named=True))


def _update_match_cache(
    self: TransitionManager, match_id: int, **updates: object
) -> None:
    """Patch specific columns on a cached match row."""
    df = self._state_manager.matches_1v1_df
    rows = df.filter(pl.col("id") == match_id)
    if rows.is_empty():
        return

    row = rows.row(0, named=True)
    row.update(updates)
    self._state_manager.matches_1v1_df = df.filter(pl.col("id") != match_id).vstack(
        pl.DataFrame([row]).cast(df.schema)
    )


def _get_player_location(self: TransitionManager, discord_uid: int) -> str | None:
    df = self._state_manager.players_df
    rows = df.filter(pl.col("discord_uid") == discord_uid)
    if rows.is_empty():
        return None
    return rows.row(0, named=True).get("location")


def _get_player_nationality(self: TransitionManager, discord_uid: int) -> str | None:
    df = self._state_manager.players_df
    rows = df.filter(pl.col("discord_uid") == discord_uid)
    if rows.is_empty():
        return None
    return rows.row(0, named=True).get("nationality")


def _get_player_letter_rank(
    self: TransitionManager, discord_uid: int, race: str
) -> str:
    """Look up a player's letter rank from the current leaderboard.

    Falls back to "U" (unranked) if the player is not on the leaderboard.
    """
    for entry in self._state_manager.leaderboard_1v1:
        if entry["discord_uid"] == discord_uid and entry["race"] == race:
            return entry["letter_rank"]
    logger.warning(
        f"Letter rank not found for player {discord_uid} race {race}, "
        f"falling back to 'U' (unranked)"
    )
    return "U"
