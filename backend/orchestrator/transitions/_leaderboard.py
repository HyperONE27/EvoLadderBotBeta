"""Leaderboard rebuild and dirty-flag management."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from backend.algorithms.leaderboard import build_leaderboard_1v1

if TYPE_CHECKING:
    from backend.orchestrator.transitions import TransitionManager

logger = structlog.get_logger(__name__)


def rebuild_leaderboard(self: TransitionManager) -> None:
    """Recompute the 1v1 leaderboard from current DataFrames."""
    self._state_manager.leaderboard_1v1 = build_leaderboard_1v1(
        self._state_manager.mmrs_1v1_df,
        self._state_manager.players_df,
    )
    self._leaderboard_dirty = True
    logger.info(
        f"Leaderboard rebuilt: {len(self._state_manager.leaderboard_1v1)} entries"
    )


def consume_leaderboard_dirty(self: TransitionManager) -> bool:
    """Return whether the leaderboard was rebuilt since last check, then reset."""
    dirty = self._leaderboard_dirty
    self._leaderboard_dirty = False
    return dirty
