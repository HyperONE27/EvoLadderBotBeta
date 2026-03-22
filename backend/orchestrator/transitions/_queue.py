"""Queue join/leave transitions for 1v1 and 2v2."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import structlog

from backend.algorithms.ratings_1v1 import get_default_mmr
from backend.domain_types.ephemeral import QueueEntry1v1, QueueEntry2v2
from common.datetime_helpers import utc_now

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


# ==================================================================
# 2v2 queue
# ==================================================================


def _handle_missing_mmr_2v2(
    self: TransitionManager,
    uid_1: int,
    uid_2: int,
    name_1: str,
    name_2: str,
) -> dict:
    """Return the 2v2 MMR row for a pair, creating it with default MMR if needed.

    UIDs are normalized internally (smaller first).
    """
    p1_uid, p2_uid = min(uid_1, uid_2), max(uid_1, uid_2)
    p1_name = name_1 if uid_1 == p1_uid else name_2
    p2_name = name_2 if uid_2 == p2_uid else name_1

    df = self._state_manager.mmrs_2v2_df
    rows = df.filter(
        (pl.col("player_1_discord_uid") == p1_uid)
        & (pl.col("player_2_discord_uid") == p2_uid)
    )
    if not rows.is_empty():
        return rows.row(0, named=True)

    logger.info(f"Creating default 2v2 MMR row for pair ({p1_uid}, {p2_uid})")
    created = self._db_writer.add_mmr_2v2(
        p1_uid, p2_uid, p1_name, p2_name, get_default_mmr()
    )
    self._state_manager.mmrs_2v2_df = df.vstack(pl.DataFrame([created]).cast(df.schema))
    return created


def join_queue_2v2(
    self: TransitionManager,
    discord_uid: int,
    discord_username: str,
    bw_race: str | None,
    sc2_race: str | None,
    map_vetoes: list[str],
) -> tuple[bool, str | None]:
    """Add a player to the 2v2 queue.

    The player must be ``in_party``.  Looks up their party partner,
    ensures a ``mmrs_2v2`` row exists for the pair, and appends a
    ``QueueEntry2v2`` to the in-memory queue.
    """
    player = self._handle_missing_player(discord_uid, discord_username)
    if player["player_status"] != "in_party":
        return (
            False,
            f"Cannot queue for 2v2: player status is '{player['player_status']}'.",
        )

    if bw_race is None and sc2_race is None:
        return False, "At least one race must be selected."

    # Find the party.
    party = self.get_party(discord_uid)
    if party is None:
        return False, "You are not in a party."

    partner_uid = (
        party["member_discord_uid"]
        if discord_uid == party["leader_discord_uid"]
        else party["leader_discord_uid"]
    )

    player_name: str = player.get("player_name") or discord_username
    nationality: str = player.get("nationality") or ""
    location: str | None = player.get("location")

    # Look up partner name.
    partner_row = self._state_manager.players_df.filter(
        pl.col("discord_uid") == partner_uid
    )
    partner_name = (
        partner_row.row(0, named=True).get("player_name", "")
        if not partner_row.is_empty()
        else ""
    )

    # Ensure MMR row exists for this pair.
    mmr_row = _handle_missing_mmr_2v2(
        self, discord_uid, partner_uid, player_name, partner_name
    )
    team_mmr: int = mmr_row["mmr"]

    # Look up team letter rank from 2v2 leaderboard.
    p1_uid = min(discord_uid, partner_uid)
    p2_uid = max(discord_uid, partner_uid)
    team_letter_rank = "U"
    for lb_entry in self._state_manager.leaderboard_2v2:
        if (
            lb_entry["player_1_discord_uid"] == p1_uid
            and lb_entry["player_2_discord_uid"] == p2_uid
        ):
            team_letter_rank = lb_entry["letter_rank"]
            break

    queue_entry = QueueEntry2v2(
        discord_uid=discord_uid,
        player_name=player_name,
        party_partner_discord_uid=partner_uid,
        bw_race=bw_race,
        sc2_race=sc2_race,
        nationality=nationality,
        location=location,
        team_mmr=team_mmr,
        team_letter_rank=team_letter_rank,
        map_vetoes=map_vetoes,
        joined_at=utc_now(),
        wait_cycles=0,
    )
    self._state_manager.queue_2v2.append(queue_entry)
    self._set_player_status(discord_uid, "queueing", match_mode="2v2")

    logger.info(f"Player {player_name} ({discord_uid}) joined the 2v2 queue")
    return True, None


def leave_queue_2v2(
    self: TransitionManager, discord_uid: int
) -> tuple[bool, str | None]:
    """Remove a player from the 2v2 queue and return them to in_party."""
    queue = self._state_manager.queue_2v2
    before = len(queue)
    self._state_manager.queue_2v2 = [
        e for e in queue if e["discord_uid"] != discord_uid
    ]
    if len(self._state_manager.queue_2v2) == before:
        return False, "Player is not in the 2v2 queue."

    # Return to in_party (the party persists; only the queue entry is removed).
    self._set_player_status(discord_uid, "in_party", match_mode="2v2")
    logger.info(f"Player {discord_uid} left the 2v2 queue")
    return True, None
