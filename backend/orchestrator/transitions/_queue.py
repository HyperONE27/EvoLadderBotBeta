"""Queue join/leave transitions for 1v1."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from common.datetime_helpers import utc_now
from backend.domain_types.ephemeral import QueueEntry1v1

if TYPE_CHECKING:
    from backend.orchestrator.transitions import TransitionManager

logger = structlog.get_logger(__name__)


def join_queue_1v1(
    self: TransitionManager,
    discord_uid: int,
    discord_username: str,
    bw_race: str | None,
    sc2_race: str | None,
    bw_mmr: int | None,
    sc2_mmr: int | None,
    map_vetoes: list[str],
) -> tuple[bool, str | None]:
    """Add a player to the 1v1 queue.

    Validates that the player is idle, ensures MMR rows exist for the
    chosen races, then appends a ``QueueEntry1v1`` to the in-memory
    queue and sets ``player_status`` to ``'queueing'``.
    """
    player = self._handle_missing_player(discord_uid, discord_username)
    if player["player_status"] != "idle":
        return False, f"Cannot queue: player status is '{player['player_status']}'."

    if bw_race is None and sc2_race is None:
        return False, "At least one race must be selected."

    player_name: str = player.get("player_name") or discord_username
    nationality: str | None = player.get("nationality")

    # Ensure MMR rows exist; use provided values if given, else look up/create.
    actual_bw_mmr: int | None = None
    actual_sc2_mmr: int | None = None

    if bw_race is not None:
        mmr_row = self._handle_missing_mmr_1v1(discord_uid, player_name, bw_race)
        actual_bw_mmr = bw_mmr if bw_mmr is not None else mmr_row["mmr"]

    if sc2_race is not None:
        mmr_row = self._handle_missing_mmr_1v1(discord_uid, player_name, sc2_race)
        actual_sc2_mmr = sc2_mmr if sc2_mmr is not None else mmr_row["mmr"]

    # Derive letter ranks from the current leaderboard state.
    # Players not yet in the leaderboard (games_played == 0) get "U".
    leaderboard_lookup: dict[tuple[int, str], str] = {
        (e["discord_uid"], e["race"]): e["letter_rank"]
        for e in self._state_manager.leaderboard_1v1
    }
    bw_letter_rank = (
        leaderboard_lookup.get((discord_uid, bw_race), "U") if bw_race else None
    )
    sc2_letter_rank = (
        leaderboard_lookup.get((discord_uid, sc2_race), "U") if sc2_race else None
    )

    entry = QueueEntry1v1(
        discord_uid=discord_uid,
        player_name=player_name,
        bw_race=bw_race,
        sc2_race=sc2_race,
        bw_mmr=actual_bw_mmr,
        sc2_mmr=actual_sc2_mmr,
        bw_letter_rank=bw_letter_rank,
        sc2_letter_rank=sc2_letter_rank,
        nationality=nationality,
        map_vetoes=map_vetoes,
        joined_at=utc_now(),
        wait_cycles=0,
    )
    self._state_manager.queue_1v1.append(entry)
    self._set_player_status(discord_uid, "queueing", match_mode="1v1")

    logger.info(f"Player {player_name} ({discord_uid}) joined the 1v1 queue")
    return True, None


def leave_queue_1v1(
    self: TransitionManager, discord_uid: int
) -> tuple[bool, str | None]:
    """Remove a player from the 1v1 queue and reset their status to idle."""
    queue = self._state_manager.queue_1v1
    before = len(queue)
    self._state_manager.queue_1v1 = [
        e for e in queue if e["discord_uid"] != discord_uid
    ]
    if len(self._state_manager.queue_1v1) == before:
        return False, "Player is not in the queue."

    self._set_player_status(discord_uid, "idle")
    logger.info(f"Player {discord_uid} left the 1v1 queue")
    return True, None
