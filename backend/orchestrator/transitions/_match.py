"""Matchmaking wave, match creation, confirmation, abort, timeout, reporting,
and shared resolution helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import polars as pl
import structlog

from backend.algorithms.match_params import resolve_match_params
from backend.algorithms.matchmaker import run_matchmaking_wave
from backend.algorithms.ratings_1v1 import get_new_ratings
from backend.core.config import (
    BASE_MMR_WINDOW,
    CURRENT_SEASON,
    MMR_WINDOW_GROWTH_PER_CYCLE,
)
from backend.domain_types.dataframes import Matches1v1Row, row_as
from backend.domain_types.ephemeral import (
    MatchCandidate1v1,
    MatchParams1v1,
    QueueEntry1v1,
)
from common.config import ABANDON_TIMEOUT_MINUTES, ABORT_TIMEOUT_MINUTES
from common.datetime_helpers import to_iso, utc_now

if TYPE_CHECKING:
    from backend.orchestrator.transitions import TransitionManager

logger = structlog.get_logger(__name__)


# ==================================================================
# Queue entry serialization (for event logging)
# ==================================================================


def _serialize_queue_entry_1v1(entry: QueueEntry1v1) -> dict[str, object]:
    """Convert a 1v1 queue entry to a JSON-safe dict for event_data."""
    return {
        "discord_uid": entry["discord_uid"],
        "player_name": entry["player_name"],
        "bw_race": entry["bw_race"],
        "sc2_race": entry["sc2_race"],
        "bw_mmr": entry["bw_mmr"],
        "sc2_mmr": entry["sc2_mmr"],
        "bw_letter_rank": entry["bw_letter_rank"],
        "sc2_letter_rank": entry["sc2_letter_rank"],
        "nationality": entry["nationality"],
        "map_vetoes": entry["map_vetoes"],
        "joined_at": to_iso(dt=entry["joined_at"]),
        "wait_cycles": entry["wait_cycles"],
        "mmr_window": BASE_MMR_WINDOW
        + entry["wait_cycles"] * MMR_WINDOW_GROWTH_PER_CYCLE,
    }


# ==================================================================
# Matchmaking wave
# ==================================================================


def run_matchmaking_wave_method(
    self: TransitionManager,
    queue_snapshot: list[QueueEntry1v1],
) -> list[Matches1v1Row]:
    """Run one matchmaking wave and create match rows for every pair found.

    1. Calls ``algorithms/matchmaker.run_matchmaking_wave`` (pure).
    2. For each candidate, calls ``algorithms/match_params.resolve_match_params`` (pure).
    3. Creates DB + cache rows for every match; updates player statuses;
       removes matched players from the queue.

    Returns the list of newly created ``Matches1v1Row`` dicts.
    """
    # Derive pool diagnostics before the wave.
    bw_only_count = sum(
        1 for e in queue_snapshot if e["bw_race"] is not None and e["sc2_race"] is None
    )
    sc2_only_count = sum(
        1 for e in queue_snapshot if e["sc2_race"] is not None and e["bw_race"] is None
    )
    both_count = sum(
        1
        for e in queue_snapshot
        if e["bw_race"] is not None and e["sc2_race"] is not None
    )

    remaining, candidates = run_matchmaking_wave(queue_snapshot)

    # Replace the queue with unmatched players (wait_cycles already incremented).
    self._state_manager.queue_1v1 = remaining

    if not candidates:
        return []

    created_matches: list[Matches1v1Row] = []

    for candidate in candidates:
        try:
            match_row = _create_match_from_candidate(self, candidate)
            created_matches.append(match_row)
        except Exception:
            logger.exception(
                "Failed to create match for candidate "
                f"{candidate['player_1_discord_uid']} vs "
                f"{candidate['player_2_discord_uid']}"
            )

    # Build matched pair details from the candidates that succeeded.
    matched_pairs_data = [
        {
            "match_id": m["id"],
            "player_1_discord_uid": m["player_1_discord_uid"],
            "player_2_discord_uid": m["player_2_discord_uid"],
            "player_1_name": m["player_1_name"],
            "player_2_name": m["player_2_name"],
            "player_1_race": m["player_1_race"],
            "player_2_race": m["player_2_race"],
            "player_1_mmr": m["player_1_mmr"],
            "player_2_mmr": m["player_2_mmr"],
            "mmr_diff": abs(m["player_1_mmr"] - m["player_2_mmr"]),
            "map_name": m["map_name"],
            "server_name": m["server_name"],
        }
        for m in created_matches
    ]

    self._db_writer.insert_event(
        {
            "discord_uid": 1,  # backend sentinel
            "event_type": "system_event",
            "action": "matchmaking_wave",
            "event_data": {
                "game_mode": "1v1",
                "queue_size": len(queue_snapshot),
                "matches_created": len(created_matches),
                "remaining_queue": len(remaining),
                # Pool diagnostics (pre-equalisation split).
                "pool_bw_only": bw_only_count,
                "pool_sc2_only": sc2_only_count,
                "pool_both": both_count,
                # Full queue snapshot.
                "queue_entries": [
                    _serialize_queue_entry_1v1(e) for e in queue_snapshot
                ],
                # Matched pairs with details.
                "matched_pairs": matched_pairs_data,
                # Unmatched players (wait_cycles already incremented by wave).
                "unmatched": [_serialize_queue_entry_1v1(e) for e in remaining],
            },
        }
    )

    logger.info(
        f"Matchmaking wave complete: {len(created_matches)} matches created, "
        f"{len(remaining)} players still in queue"
    )
    return created_matches


def _create_match_from_candidate(
    self: TransitionManager, candidate: MatchCandidate1v1
) -> Matches1v1Row:
    """Resolve parameters, write the match row, and update player states."""
    p1_uid = candidate["player_1_discord_uid"]
    p2_uid = candidate["player_2_discord_uid"]

    # Resolve locations — fall back to opponent's location if missing.
    # The candidate carries each player's region as a snapshot from
    # queue-join time (see backend/algorithms/matchmaker._to_match_candidate).
    p1_loc = candidate["player_1_location"]
    p2_loc = candidate["player_2_location"]

    if p1_loc is None and p2_loc is not None:
        logger.error(
            "match_location_fallback: player_1 location missing, "
            "borrowing from opponent",
            player_1_discord_uid=candidate["player_1_discord_uid"],
            player_2_discord_uid=candidate["player_2_discord_uid"],
            borrowed_from_player_2=p2_loc,
        )
        p1_loc = p2_loc
    elif p2_loc is None and p1_loc is not None:
        logger.error(
            "match_location_fallback: player_2 location missing, "
            "borrowing from opponent",
            player_1_discord_uid=candidate["player_1_discord_uid"],
            player_2_discord_uid=candidate["player_2_discord_uid"],
            borrowed_from_player_1=p1_loc,
        )
        p2_loc = p1_loc
    elif p1_loc is None and p2_loc is None:
        # Both missing — pick a sensible fallback.  The cross-table
        # requires valid region codes so we can't just pass None.
        logger.error(
            "match_location_fallback: BOTH players missing location, "
            "defaulting to NAC — investigate the players' profiles",
            player_1_discord_uid=candidate["player_1_discord_uid"],
            player_2_discord_uid=candidate["player_2_discord_uid"],
        )
        p1_loc = "NAC"
        p2_loc = "NAC"

    # At this point both are guaranteed non-None by the if/elif chain.
    if p1_loc is None or p2_loc is None:
        raise ValueError(
            f"Player location is None after resolution for candidate "
            f"{candidate['player_1_discord_uid']} vs {candidate['player_2_discord_uid']}"
        )

    params: MatchParams1v1 = resolve_match_params(
        candidate,
        player_1_location=p1_loc,
        player_2_location=p2_loc,
        maps=self._state_manager.maps,
        cross_table=self._state_manager.cross_table,
        season=CURRENT_SEASON,
    )

    now = utc_now()

    created = self._db_writer.add_match_1v1(
        player_1_discord_uid=p1_uid,
        player_2_discord_uid=p2_uid,
        player_1_name=candidate["player_1_name"],
        player_2_name=candidate["player_2_name"],
        player_1_race=candidate["player_1_race"],
        player_2_race=candidate["player_2_race"],
        player_1_mmr=candidate["player_1_mmr"],
        player_2_mmr=candidate["player_2_mmr"],
        map_name=params["map_name"],
        server_name=params["server_name"],
        assigned_at=now,
    )

    # Update in-memory matches DataFrame.
    df = self._state_manager.matches_1v1_df
    self._state_manager.matches_1v1_df = df.vstack(
        pl.DataFrame([created]).cast(df.schema)
    )

    match_id: int = created["id"]

    # Update both players to in_match.
    self._set_player_status(p1_uid, "in_match", match_mode="1v1", match_id=match_id)
    self._set_player_status(p2_uid, "in_match", match_mode="1v1", match_id=match_id)

    # Initialise confirmation tracking.
    self._confirmations[match_id] = set()

    self._db_writer.insert_event(
        {
            "discord_uid": 1,  # backend sentinel
            "event_type": "match_event",
            "action": "match_found",
            "game_mode": "1v1",
            "match_id": match_id,
            "event_data": {
                "game_mode": "1v1",
                "match_id": match_id,
                "p1_uid": p1_uid,
                "p2_uid": p2_uid,
                "p1_name": candidate["player_1_name"],
                "p2_name": candidate["player_2_name"],
                "p1_race": candidate["player_1_race"],
                "p2_race": candidate["player_2_race"],
                "p1_mmr": candidate["player_1_mmr"],
                "p2_mmr": candidate["player_2_mmr"],
                "map_name": params["map_name"],
                "server_name": params["server_name"],
            },
        }
    )

    logger.info(
        f"Match #{match_id} created: "
        f"{candidate['player_1_name']} vs {candidate['player_2_name']} "
        f"on {params['map_name']} @ {params['server_name']}"
    )

    return row_as(Matches1v1Row, created)


# ==================================================================
# Match confirmation
# ==================================================================


def confirm_match(
    self: TransitionManager, match_id: int, discord_uid: int
) -> tuple[bool, bool]:
    """Record that a player has confirmed a match.

    Returns ``(success, both_confirmed)``.
    """
    if match_id not in self._confirmations:
        self._confirmations[match_id] = set()

    already_confirmed = len(self._confirmations[match_id]) >= 2
    self._confirmations[match_id].add(discord_uid)
    both = not already_confirmed and len(self._confirmations[match_id]) >= 2

    self._db_writer.insert_event(
        {
            "discord_uid": discord_uid,  # acting player
            "event_type": "match_event",
            "action": "match_confirmed",
            "game_mode": "1v1",
            "match_id": match_id,
            "event_data": {
                "game_mode": "1v1",
                "match_id": match_id,
                "both_confirmed": both,
            },
        }
    )

    logger.info(
        f"Player {discord_uid} confirmed match #{match_id} (both_confirmed={both})"
    )
    return True, both


def is_match_confirmed(self: TransitionManager, match_id: int) -> bool:
    return len(self._confirmations.get(match_id, set())) >= 2


# ==================================================================
# Match abort
# ==================================================================


def abort_match(
    self: TransitionManager, match_id: int, discord_uid: int
) -> tuple[bool, str | None]:
    """Abort a match.  The aborting player gets ``'abort'``, the opponent
    gets ``'no_report'``, and ``match_result`` is set to ``'abort'``.
    Both players are returned to idle.
    """
    match = self._get_match_row(match_id)
    if match is None:
        return False, "Match not found."

    if match["match_result"] is not None:
        return False, "Match already resolved."

    p1_uid = match["player_1_discord_uid"]
    p2_uid = match["player_2_discord_uid"]

    if discord_uid == p1_uid:
        p1_report, p2_report = "abort", "no_report"
    elif discord_uid == p2_uid:
        p1_report, p2_report = "no_report", "abort"
    else:
        return False, "Player is not part of this match."

    now = utc_now()
    _apply_match_resolution(
        self,
        match_id,
        match,
        "abort",
        0,
        0,
        match["player_1_mmr"],
        match["player_2_mmr"],
        now,
        player_1_report=p1_report,
        player_2_report=p2_report,
    )

    # Apply timeout penalty to the aborting player.
    timeout_until = now + timedelta(minutes=ABORT_TIMEOUT_MINUTES)
    self._set_player_status(discord_uid, "timed_out", timeout_until=timeout_until)

    self._db_writer.insert_event(
        {
            "discord_uid": discord_uid,  # acting player
            "event_type": "match_event",
            "action": "match_aborted",
            "game_mode": "1v1",
            "match_id": match_id,
            "event_data": {
                "game_mode": "1v1",
                "match_id": match_id,
                "aborter_uid": discord_uid,
                "p1_uid": p1_uid,
                "p2_uid": p2_uid,
                "timeout_minutes": ABORT_TIMEOUT_MINUTES,
            },
        }
    )

    logger.info(f"Match #{match_id} aborted by player {discord_uid}")
    return True, None


# ==================================================================
# Confirmation timeout (abandoned)
# ==================================================================


def handle_confirmation_timeout(
    self: TransitionManager, match_id: int
) -> tuple[bool, str | None]:
    """Handle expiry of the confirmation window.

    Players who did *not* confirm get ``'abandoned'``; players who did
    confirm get ``'no_report'``.  ``match_result`` is set to ``'abandoned'``.
    """
    match = self._get_match_row(match_id)
    if match is None:
        return False, "Match not found."

    if match["match_result"] is not None:
        return False, "Match already resolved."

    confirmed = self._confirmations.get(match_id, set())
    p1_uid = match["player_1_discord_uid"]
    p2_uid = match["player_2_discord_uid"]

    p1_report = "no_report" if p1_uid in confirmed else "abandoned"
    p2_report = "no_report" if p2_uid in confirmed else "abandoned"

    now = utc_now()
    _apply_match_resolution(
        self,
        match_id,
        match,
        "abandoned",
        0,
        0,
        match["player_1_mmr"],
        match["player_2_mmr"],
        now,
        player_1_report=p1_report,
        player_2_report=p2_report,
    )

    # Apply timeout penalty to players who did not confirm.
    timeout_until = now + timedelta(minutes=ABANDON_TIMEOUT_MINUTES)
    for uid, report in ((p1_uid, p1_report), (p2_uid, p2_report)):
        if report == "abandoned":
            self._set_player_status(uid, "timed_out", timeout_until=timeout_until)

    self._db_writer.insert_event(
        {
            "discord_uid": 1,  # backend sentinel — timeout, no acting user
            "event_type": "match_event",
            "action": "match_abandoned",
            "game_mode": "1v1",
            "match_id": match_id,
            "event_data": {
                "game_mode": "1v1",
                "match_id": match_id,
                "p1_uid": p1_uid,
                "p2_uid": p2_uid,
                "p1_report": p1_report,
                "p2_report": p2_report,
                "timeout_minutes": ABANDON_TIMEOUT_MINUTES,
            },
        }
    )

    logger.info(f"Match #{match_id} abandoned (confirmation timeout)")
    return True, None


# ==================================================================
# Match result reporting
# ==================================================================


def report_match_result(
    self: TransitionManager,
    match_id: int,
    discord_uid: int,
    report: str,
) -> tuple[bool, str | None, Matches1v1Row | None]:
    """Record one player's result report.

    If both players have now reported and agree, MMR is calculated, the
    match is finalised, and both players return to idle.

    Returns ``(success, message, finalised_match_or_none)``.
    """
    valid_reports = {"player_1_win", "player_2_win", "draw"}
    if report not in valid_reports:
        return False, f"Invalid report value: {report!r}", None

    match = self._get_match_row(match_id)
    if match is None:
        return False, "Match not found.", None
    if match["match_result"] is not None:
        return False, "Match already resolved.", None

    p1_uid = match["player_1_discord_uid"]
    p2_uid = match["player_2_discord_uid"]

    # Determine which column to write.
    if discord_uid == p1_uid:
        self._db_writer.update_match_1v1_report(match_id, player_1_report=report)
        self._update_match_cache(match_id, player_1_report=report)
    elif discord_uid == p2_uid:
        self._db_writer.update_match_1v1_report(match_id, player_2_report=report)
        self._update_match_cache(match_id, player_2_report=report)
    else:
        return False, "Player is not part of this match.", None

    # Re-fetch to see both reports.
    match = self._get_match_row(match_id)
    if match is None:
        raise RuntimeError(f"Match #{match_id} disappeared after report update")

    p1_report = match["player_1_report"]
    p2_report = match["player_2_report"]

    # If only one player has reported so far, wait.
    if p1_report is None or p2_report is None:
        logger.info(
            f"Match #{match_id}: player {discord_uid} reported '{report}', "
            "waiting for opponent"
        )
        return True, None, None

    # Both reports are in — check agreement.
    if p1_report == p2_report:
        finalised = _finalise_match(self, match_id, match, p1_report)
        return True, None, finalised
    else:
        # Conflict — mark as conflict, no MMR changes.
        finalised = _handle_conflict(self, match_id, match)
        return True, "Reports conflict — match marked as conflict.", finalised


# ==================================================================
# Shared match resolution helpers
# ==================================================================


def _calculate_mmr_changes(
    self: TransitionManager,
    match: Matches1v1Row,
    result: str,
) -> tuple[int, int, int, int]:
    """Calculate MMR changes from snapshotted match MMRs.

    Returns ``(new_p1_mmr, new_p2_mmr, p1_change, p2_change)``.
    """
    result_code_map = {"player_1_win": 1, "player_2_win": 2, "draw": 0}
    result_code = result_code_map[result]
    new_p1_mmr, new_p2_mmr = get_new_ratings(
        match["player_1_mmr"], match["player_2_mmr"], result_code
    )
    p1_change = new_p1_mmr - match["player_1_mmr"]
    p2_change = new_p2_mmr - match["player_2_mmr"]
    return new_p1_mmr, new_p2_mmr, p1_change, p2_change


def _apply_match_resolution(
    self: TransitionManager,
    match_id: int,
    match: Matches1v1Row,
    result: str,
    p1_change: int,
    p2_change: int,
    new_p1_mmr: int,
    new_p2_mmr: int,
    now: datetime,
    *,
    player_1_report: str | None = None,
    player_2_report: str | None = None,
    admin_intervened: bool = False,
    admin_discord_uid: int | None = None,
) -> Matches1v1Row:
    """Write match result, update MMRs, reset players to idle, and return
    the updated match row.

    This is the single code path for all non-abort/non-abandoned match
    resolutions (player agreement, admin resolve, replay auto-resolve).
    """
    p1_uid = match["player_1_discord_uid"]
    p2_uid = match["player_2_discord_uid"]
    p1_race = match["player_1_race"]
    p2_race = match["player_2_race"]

    # Build match-row updates first.
    cache_kwargs: dict[str, object] = {
        "match_result": result,
        "player_1_mmr_change": p1_change,
        "player_2_mmr_change": p2_change,
        "completed_at": now,
    }

    if player_1_report is not None:
        cache_kwargs["player_1_report"] = player_1_report
    if player_2_report is not None:
        cache_kwargs["player_2_report"] = player_2_report

    if admin_intervened:
        cache_kwargs["admin_intervened"] = True
        cache_kwargs["admin_discord_uid"] = admin_discord_uid

    # Update the in-memory match row BEFORE computing game stats so that
    # count_game_stats sees the current match's result.
    self._update_match_cache(match_id, **cache_kwargs)

    # Now compute MMR updates (game stats will include the current match).
    p1_mmr_update = self._compute_mmr_update(
        p1_uid, p1_race, new_p1_mmr, result, is_player_1=True, now=now
    )
    p2_mmr_update = self._compute_mmr_update(
        p2_uid, p2_race, new_p2_mmr, result, is_player_1=False, now=now
    )

    # Persist to DB.
    if admin_intervened:
        self._db_writer.admin_resolve_match_1v1(
            match_id,
            match_result=result,
            player_1_mmr_change=p1_change,
            player_2_mmr_change=p2_change,
            admin_discord_uid=admin_discord_uid or 0,
            completed_at=now,
        )
    else:
        self._db_writer.finalise_match_1v1(
            match_id,
            match_result=result,
            player_1_mmr_change=p1_change,
            player_2_mmr_change=p2_change,
            completed_at=now,
            player_1_report=player_1_report,
            player_2_report=player_2_report,
        )

    # Write both MMR rows in a single upsert.
    mmr_updates = [u for u in (p1_mmr_update, p2_mmr_update) if u is not None]
    if mmr_updates:
        self._db_writer.batch_update_mmrs_1v1(mmr_updates)

    # Update MMR caches.
    if p1_mmr_update is not None:
        self._apply_mmr_cache_update(p1_uid, p1_race, p1_mmr_update)
    if p2_mmr_update is not None:
        self._apply_mmr_cache_update(p2_uid, p2_race, p2_mmr_update)

    # Return both players to idle.
    self._set_player_status(p1_uid, "idle")
    self._set_player_status(p2_uid, "idle")
    self._confirmations.pop(match_id, None)

    self.rebuild_leaderboard()

    updated_match = self._get_match_row(match_id)
    if updated_match is None:
        raise RuntimeError(f"Match #{match_id} not found after resolution")
    return updated_match


def _finalise_match(
    self: TransitionManager,
    match_id: int,
    match: Matches1v1Row,
    agreed_result: str,
) -> Matches1v1Row:
    """Both players agree — calculate MMR, write everything, return to idle."""
    now = utc_now()
    new_p1_mmr, new_p2_mmr, p1_change, p2_change = _calculate_mmr_changes(
        self, match, agreed_result
    )

    updated = _apply_match_resolution(
        self,
        match_id,
        match,
        agreed_result,
        p1_change,
        p2_change,
        new_p1_mmr,
        new_p2_mmr,
        now,
    )

    self._db_writer.insert_event(
        {
            "discord_uid": 1,  # backend sentinel — both-agree auto-resolution
            "event_type": "match_event",
            "action": "match_completed",
            "game_mode": "1v1",
            "match_id": match_id,
            "event_data": {
                "game_mode": "1v1",
                "match_id": match_id,
                "result": agreed_result,
                "p1_uid": match["player_1_discord_uid"],
                "p2_uid": match["player_2_discord_uid"],
                "p1_mmr_change": p1_change,
                "p2_mmr_change": p2_change,
            },
        }
    )

    logger.info(
        f"Match #{match_id} finalised: {agreed_result} "
        f"(p1 {match['player_1_mmr']}→{new_p1_mmr}, "
        f"p2 {match['player_2_mmr']}→{new_p2_mmr})"
    )
    return updated


def _handle_conflict(
    self: TransitionManager, match_id: int, match: Matches1v1Row
) -> Matches1v1Row:
    """Reports disagree — mark as conflict, no MMR changes, return to idle."""
    now = utc_now()

    updated = _apply_match_resolution(
        self,
        match_id,
        match,
        "conflict",
        0,
        0,
        match["player_1_mmr"],
        match["player_2_mmr"],
        now,
    )

    self._db_writer.insert_event(
        {
            "discord_uid": 1,  # backend sentinel — conflict auto-detected
            "event_type": "match_event",
            "action": "match_conflict",
            "game_mode": "1v1",
            "match_id": match_id,
            "event_data": {
                "game_mode": "1v1",
                "match_id": match_id,
                "p1_uid": match["player_1_discord_uid"],
                "p2_uid": match["player_2_discord_uid"],
                "p1_report": match["player_1_report"],
                "p2_report": match["player_2_report"],
            },
        }
    )

    logger.info(f"Match #{match_id} marked as conflict (conflicting reports)")
    return updated
