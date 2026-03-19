"""MMR helper methods for transition operations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import polars as pl
import structlog

from backend.algorithms.game_stats import count_game_stats
from backend.algorithms.ratings_1v1 import get_default_mmr

if TYPE_CHECKING:
    from backend.orchestrator.transitions import TransitionManager

logger = structlog.get_logger(__name__)


def _handle_missing_mmr_1v1(
    self: TransitionManager, discord_uid: int, player_name: str, race: str
) -> dict:
    """Return the MMR row, creating it with default MMR if it doesn't exist."""
    df = self._state_manager.mmrs_1v1_df

    rows = df.filter((pl.col("discord_uid") == discord_uid) & (pl.col("race") == race))
    if not rows.is_empty():
        return rows.row(0, named=True)

    logger.info(
        f"Creating default MMR row for {player_name} ({discord_uid}), race={race}"
    )
    created = self._db_writer.add_mmr_1v1(
        discord_uid, player_name, race, get_default_mmr()
    )
    self._state_manager.mmrs_1v1_df = df.vstack(pl.DataFrame([created]).cast(df.schema))
    return created


def _compute_mmr_update(
    self: TransitionManager,
    discord_uid: int,
    race: str,
    new_mmr: int,
    agreed_result: str,
    *,
    is_player_1: bool,
    now: datetime,
) -> dict | None:
    """Return a fully-populated MMR row dict for the given player, or None if
    no row exists.  Does not touch the DB or the cache.

    Game stats (games_played/won/lost/drawn) are recalculated from the
    matches_1v1 ground truth rather than incremented, so admin re-resolves
    cannot desync the counters.
    """
    df = self._state_manager.mmrs_1v1_df
    rows = df.filter((pl.col("discord_uid") == discord_uid) & (pl.col("race") == race))
    if rows.is_empty():
        return None

    current = rows.row(0, named=True)
    stats = count_game_stats(self._state_manager.matches_1v1_df, discord_uid, race)

    return {
        **current,
        "mmr": new_mmr,
        "games_played": stats["games_played"],
        "games_won": stats["games_won"],
        "games_lost": stats["games_lost"],
        "games_drawn": stats["games_drawn"],
        "last_played_at": now,
    }


def _apply_mmr_cache_update(
    self: TransitionManager, discord_uid: int, race: str, updated: dict
) -> None:
    """Swap in a pre-computed MMR row in the in-memory cache."""
    df = self._state_manager.mmrs_1v1_df
    self._state_manager.mmrs_1v1_df = df.filter(
        ~((pl.col("discord_uid") == discord_uid) & (pl.col("race") == race))
    ).vstack(pl.DataFrame([updated]).cast(df.schema))


def _set_mmr_cache_value(
    self: TransitionManager, discord_uid: int, race: str, mmr: int
) -> None:
    """Set only the MMR value on an existing cache row (no stat changes)."""
    df = self._state_manager.mmrs_1v1_df
    rows = df.filter((pl.col("discord_uid") == discord_uid) & (pl.col("race") == race))
    if rows.is_empty():
        return
    updated = rows.row(0, named=True)
    updated["mmr"] = mmr
    self._state_manager.mmrs_1v1_df = df.filter(
        ~((pl.col("discord_uid") == discord_uid) & (pl.col("race") == race))
    ).vstack(pl.DataFrame([updated]).cast(df.schema))


def _recalculate_game_stats(
    self: TransitionManager, discord_uid: int, race: str
) -> None:
    """Recalculate games_played/won/lost/drawn from matches_1v1 ground truth
    and write to both DB and in-memory cache."""
    df = self._state_manager.mmrs_1v1_df
    rows = df.filter((pl.col("discord_uid") == discord_uid) & (pl.col("race") == race))
    if rows.is_empty():
        return

    stats = count_game_stats(self._state_manager.matches_1v1_df, discord_uid, race)

    # DB write
    self._db_writer.update_mmr_1v1_game_stats(
        discord_uid,
        race,
        games_played=stats["games_played"],
        games_won=stats["games_won"],
        games_lost=stats["games_lost"],
        games_drawn=stats["games_drawn"],
    )

    # Cache update
    updated = rows.row(0, named=True)
    updated["games_played"] = stats["games_played"]
    updated["games_won"] = stats["games_won"]
    updated["games_lost"] = stats["games_lost"]
    updated["games_drawn"] = stats["games_drawn"]
    self._state_manager.mmrs_1v1_df = df.filter(
        ~((pl.col("discord_uid") == discord_uid) & (pl.col("race") == race))
    ).vstack(pl.DataFrame([updated]).cast(df.schema))
