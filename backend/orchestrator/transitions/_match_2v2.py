"""2v2 matchmaking wave, match creation, confirmation, abort, timeout, and reporting."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import polars as pl
import structlog

from backend.algorithms.game_stats import count_game_stats_2v2
from backend.algorithms.match_params_2v2 import resolve_match_params_2v2
from backend.algorithms.matchmaker_2v2 import run_matchmaking_wave_2v2
from backend.algorithms.ratings_1v1 import get_new_ratings
from backend.core.config import CURRENT_SEASON
from backend.domain_types.dataframes import Matches2v2Row, row_as
from backend.domain_types.ephemeral import MatchCandidate2v2, MatchParams2v2
from common.datetime_helpers import utc_now

if TYPE_CHECKING:
    from backend.orchestrator.transitions import TransitionManager

logger = structlog.get_logger(__name__)

# Number of confirmations required before a 2v2 match is considered confirmed.
_REQUIRED_CONFIRMATIONS = 4


# ==================================================================
# Matchmaking wave
# ==================================================================


def run_matchmaking_wave_2v2_method(
    self: TransitionManager,
    queue_snapshot: list,
) -> list[Matches2v2Row]:
    """Run one 2v2 matchmaking wave and create match rows for every pair found.

    1. Calls ``algorithms/matchmaker_2v2.run_matchmaking_wave_2v2`` (pure).
    2. For each candidate, calls ``resolve_match_params_2v2`` (pure).
    3. Creates DB + cache rows; updates all four player statuses;
       removes matched teams from the queue.

    Returns the list of newly created ``Matches2v2Row`` dicts.
    """
    remaining, candidates = run_matchmaking_wave_2v2(queue_snapshot)

    # Replace the queue with unmatched teams (wait_cycles already incremented).
    self._state_manager.queue_2v2 = remaining

    if not candidates:
        return []

    created_matches: list[Matches2v2Row] = []

    for candidate in candidates:
        try:
            match_row = _create_match_2v2_from_candidate(self, candidate)
            created_matches.append(match_row)
        except Exception:
            logger.exception(
                "Failed to create 2v2 match for candidate "
                f"team_1={candidate['team_1_player_1_discord_uid']} vs "
                f"team_2={candidate['team_2_player_1_discord_uid']}"
            )

    self._db_writer.insert_event(
        {
            "discord_uid": 1,  # backend sentinel
            "event_type": "system_event",
            "action": "matchmaking_wave",
            "event_data": {
                "game_mode": "2v2",
                "queue_size": len(queue_snapshot),
                "matches_created": len(created_matches),
                "remaining_queue": len(remaining),
            },
        }
    )

    logger.info(
        f"2v2 matchmaking wave complete: {len(created_matches)} matches created, "
        f"{len(remaining)} teams still in queue"
    )
    return created_matches


# ==================================================================
# Match creation
# ==================================================================


def _create_match_2v2_from_candidate(
    self: TransitionManager, candidate: MatchCandidate2v2
) -> Matches2v2Row:
    """Resolve parameters, write the match row, and update player states."""
    params: MatchParams2v2 = resolve_match_params_2v2(
        candidate,
        maps=self._state_manager.maps,
        cross_table=self._state_manager.cross_table,
        season=CURRENT_SEASON,
    )

    now = utc_now()

    created = self._db_writer.add_match_2v2(
        team_1_player_1_discord_uid=candidate["team_1_player_1_discord_uid"],
        team_1_player_2_discord_uid=candidate["team_1_player_2_discord_uid"],
        team_1_player_1_name=candidate["team_1_player_1_name"],
        team_1_player_2_name=candidate["team_1_player_2_name"],
        team_1_player_1_race=candidate["team_1_player_1_race"],
        team_1_player_2_race=candidate["team_1_player_2_race"],
        team_1_mmr=candidate["team_1_mmr"],
        team_2_player_1_discord_uid=candidate["team_2_player_1_discord_uid"],
        team_2_player_2_discord_uid=candidate["team_2_player_2_discord_uid"],
        team_2_player_1_name=candidate["team_2_player_1_name"],
        team_2_player_2_name=candidate["team_2_player_2_name"],
        team_2_player_1_race=candidate["team_2_player_1_race"],
        team_2_player_2_race=candidate["team_2_player_2_race"],
        team_2_mmr=candidate["team_2_mmr"],
        map_name=params["map_name"],
        server_name=params["server_name"],
        assigned_at=now,
    )

    # Update in-memory matches DataFrame.
    df = self._state_manager.matches_2v2_df
    self._state_manager.matches_2v2_df = df.vstack(
        pl.DataFrame([created]).cast(df.schema)
    )

    match_id: int = created["id"]

    t1_p1 = candidate["team_1_player_1_discord_uid"]
    t1_p2 = candidate["team_1_player_2_discord_uid"]
    t2_p1 = candidate["team_2_player_1_discord_uid"]
    t2_p2 = candidate["team_2_player_2_discord_uid"]

    # Update all four players to in_match.
    for uid in (t1_p1, t1_p2, t2_p1, t2_p2):
        self._set_player_status(uid, "in_match", match_mode="2v2", match_id=match_id)

    # Initialise confirmation tracking (requires all 4).
    self._confirmations[match_id] = set()

    self._db_writer.insert_event(
        {
            "discord_uid": 1,  # backend sentinel
            "event_type": "match_event",
            "action": "match_found",
            "game_mode": "2v2",
            "match_id": match_id,
            "event_data": {
                "game_mode": "2v2",
                "match_id": match_id,
                "team_1_player_1_discord_uid": t1_p1,
                "team_1_player_2_discord_uid": t1_p2,
                "team_2_player_1_discord_uid": t2_p1,
                "team_2_player_2_discord_uid": t2_p2,
                "team_1_player_1_name": candidate["team_1_player_1_name"],
                "team_1_player_2_name": candidate["team_1_player_2_name"],
                "team_2_player_1_name": candidate["team_2_player_1_name"],
                "team_2_player_2_name": candidate["team_2_player_2_name"],
                "team_1_player_1_race": candidate["team_1_player_1_race"],
                "team_1_player_2_race": candidate["team_1_player_2_race"],
                "team_2_player_1_race": candidate["team_2_player_1_race"],
                "team_2_player_2_race": candidate["team_2_player_2_race"],
                "team_1_mmr": candidate["team_1_mmr"],
                "team_2_mmr": candidate["team_2_mmr"],
                "map_name": params["map_name"],
                "server_name": params["server_name"],
            },
        }
    )

    logger.info(
        f"2v2 Match #{match_id} created: "
        f"{candidate['team_1_player_1_name']}/{candidate['team_1_player_2_name']} vs "
        f"{candidate['team_2_player_1_name']}/{candidate['team_2_player_2_name']} "
        f"on {params['map_name']} @ {params['server_name']}"
    )

    return row_as(Matches2v2Row, created)


# ==================================================================
# Confirmation
# ==================================================================


def confirm_match_2v2(
    self: TransitionManager, match_id: int, discord_uid: int
) -> tuple[bool, bool]:
    """Record that a player has confirmed a 2v2 match.

    Returns ``(success, all_confirmed)``.  All four players must confirm.
    """
    match = _get_match_2v2_row(self, match_id)
    if match is None:
        return False, False

    all_uids = {
        match["team_1_player_1_discord_uid"],
        match["team_1_player_2_discord_uid"],
        match["team_2_player_1_discord_uid"],
        match["team_2_player_2_discord_uid"],
    }
    if discord_uid not in all_uids:
        return False, False

    if match_id not in self._confirmations:
        self._confirmations[match_id] = set()
    self._confirmations[match_id].add(discord_uid)
    all_confirmed = len(self._confirmations[match_id]) >= _REQUIRED_CONFIRMATIONS

    self._db_writer.insert_event(
        {
            "discord_uid": discord_uid,
            "event_type": "match_event",
            "action": "match_confirmed",
            "game_mode": "2v2",
            "match_id": match_id,
            "event_data": {
                "game_mode": "2v2",
                "match_id": match_id,
                "all_confirmed": all_confirmed,
            },
        }
    )

    logger.info(
        f"Player {discord_uid} confirmed 2v2 match #{match_id} "
        f"(confirmed={len(self._confirmations[match_id])}/{_REQUIRED_CONFIRMATIONS})"
    )
    return True, all_confirmed


def is_match_2v2_confirmed(self: TransitionManager, match_id: int) -> bool:
    return len(self._confirmations.get(match_id, set())) >= _REQUIRED_CONFIRMATIONS


# ==================================================================
# Internal helpers
# ==================================================================


def _get_match_2v2_row(self: TransitionManager, match_id: int) -> Matches2v2Row | None:
    df = self._state_manager.matches_2v2_df
    if df.is_empty():
        return None
    filtered = df.filter(pl.col("id") == match_id)
    if filtered.is_empty():
        return None
    return row_as(Matches2v2Row, filtered.row(0, named=True))


# ==================================================================
# Abort
# ==================================================================


def abort_match_2v2(
    self: TransitionManager, match_id: int, discord_uid: int
) -> tuple[bool, str | None]:
    """Abort a 2v2 match.

    Any of the four players may abort.  The aborting team gets ``'abort'``,
    the opposing team gets ``'no_report'``.  All four players return to
    ``in_party``.
    """
    match = _get_match_2v2_row(self, match_id)
    if match is None:
        return False, "Match not found."
    if match["match_result"] is not None:
        return False, "Match already resolved."

    t1_uids = {
        match["team_1_player_1_discord_uid"],
        match["team_1_player_2_discord_uid"],
    }
    t2_uids = {
        match["team_2_player_1_discord_uid"],
        match["team_2_player_2_discord_uid"],
    }

    if discord_uid in t1_uids:
        t1_report, t2_report = "abort", "no_report"
    elif discord_uid in t2_uids:
        t1_report, t2_report = "no_report", "abort"
    else:
        return False, "Player is not part of this match."

    now = utc_now()
    _apply_match_2v2_resolution(
        self,
        match_id,
        match,
        "abort",
        0,
        0,
        match["team_1_mmr"],
        match["team_2_mmr"],
        now,
        team_1_report=t1_report,
        team_2_report=t2_report,
    )

    self._db_writer.insert_event(
        {
            "discord_uid": discord_uid,
            "event_type": "match_event",
            "action": "match_aborted",
            "game_mode": "2v2",
            "match_id": match_id,
            "event_data": {
                "game_mode": "2v2",
                "match_id": match_id,
                "aborter_uid": discord_uid,
            },
        }
    )

    logger.info(f"2v2 match #{match_id} aborted by player {discord_uid}")
    return True, None


# ==================================================================
# Confirmation timeout (abandoned)
# ==================================================================


def handle_confirmation_timeout_2v2(
    self: TransitionManager, match_id: int
) -> tuple[bool, str | None]:
    """Handle expiry of the 2v2 confirmation window.

    Players who did not confirm get ``'abandoned'``; those who did get
    ``'no_report'``.  ``match_result`` is set to ``'abandoned'``.
    """
    match = _get_match_2v2_row(self, match_id)
    if match is None:
        return False, "Match not found."
    if match["match_result"] is not None:
        return False, "Match already resolved."

    confirmed = self._confirmations.get(match_id, set())

    def _team_report(uid_a: int, uid_b: int) -> str:
        return (
            "no_report" if (uid_a in confirmed or uid_b in confirmed) else "abandoned"
        )

    t1_report = _team_report(
        match["team_1_player_1_discord_uid"], match["team_1_player_2_discord_uid"]
    )
    t2_report = _team_report(
        match["team_2_player_1_discord_uid"], match["team_2_player_2_discord_uid"]
    )

    now = utc_now()
    _apply_match_2v2_resolution(
        self,
        match_id,
        match,
        "abandoned",
        0,
        0,
        match["team_1_mmr"],
        match["team_2_mmr"],
        now,
        team_1_report=t1_report,
        team_2_report=t2_report,
    )

    self._db_writer.insert_event(
        {
            "discord_uid": 1,  # backend sentinel
            "event_type": "match_event",
            "action": "match_abandoned",
            "game_mode": "2v2",
            "match_id": match_id,
            "event_data": {
                "game_mode": "2v2",
                "match_id": match_id,
                "t1_report": t1_report,
                "t2_report": t2_report,
            },
        }
    )

    logger.info(f"2v2 match #{match_id} abandoned (confirmation timeout)")
    return True, None


# ==================================================================
# Match result reporting
# ==================================================================


def report_match_result_2v2(
    self: TransitionManager,
    match_id: int,
    discord_uid: int,
    report: str,
) -> tuple[bool, str | None, Matches2v2Row | None]:
    """Record one team's result report for a 2v2 match.

    Either member of a team may submit their team's report.  If both teams
    have now reported and agree, MMR is calculated and the match is finalised.

    Returns ``(success, message, finalised_match_or_none)``.
    """
    valid_reports = {"team_1_win", "team_2_win", "draw"}
    if report not in valid_reports:
        return False, f"Invalid report value: {report!r}", None

    match = _get_match_2v2_row(self, match_id)
    if match is None:
        return False, "Match not found.", None
    if match["match_result"] is not None:
        return False, "Match already resolved.", None

    t1_uids = {
        match["team_1_player_1_discord_uid"],
        match["team_1_player_2_discord_uid"],
    }
    t2_uids = {
        match["team_2_player_1_discord_uid"],
        match["team_2_player_2_discord_uid"],
    }

    if discord_uid in t1_uids:
        self._db_writer.update_match_2v2_report(
            match_id,
            team_1_report=report,
            team_1_reporter_discord_uid=discord_uid,
        )
        _update_match_2v2_cache(
            self,
            match_id,
            team_1_report=report,
            team_1_reporter_discord_uid=discord_uid,
        )
    elif discord_uid in t2_uids:
        self._db_writer.update_match_2v2_report(
            match_id,
            team_2_report=report,
            team_2_reporter_discord_uid=discord_uid,
        )
        _update_match_2v2_cache(
            self,
            match_id,
            team_2_report=report,
            team_2_reporter_discord_uid=discord_uid,
        )
    else:
        return False, "Player is not part of this match.", None

    match = _get_match_2v2_row(self, match_id)
    if match is None:
        raise RuntimeError(f"2v2 match #{match_id} disappeared after report update")

    t1_report = match["team_1_report"]
    t2_report = match["team_2_report"]

    if t1_report is None or t2_report is None:
        logger.info(
            f"2v2 match #{match_id}: player {discord_uid} reported '{report}', "
            "waiting for opponent team"
        )
        return True, None, None

    if t1_report == t2_report:
        finalised = _finalise_match_2v2(self, match_id, match, t1_report)
        return True, None, finalised
    else:
        finalised = _handle_conflict_2v2(self, match_id, match)
        return True, "Reports conflict — match marked as conflict.", finalised


# ==================================================================
# Shared resolution helpers
# ==================================================================


def _calculate_mmr_changes_2v2(
    match: Matches2v2Row,
    result: str,
) -> tuple[int, int, int, int]:
    """Return ``(new_t1_mmr, new_t2_mmr, t1_change, t2_change)``."""
    result_code_map = {"team_1_win": 1, "team_2_win": 2, "draw": 0}
    result_code = result_code_map[result]
    new_t1_mmr, new_t2_mmr = get_new_ratings(
        match["team_1_mmr"], match["team_2_mmr"], result_code
    )
    return (
        new_t1_mmr,
        new_t2_mmr,
        new_t1_mmr - match["team_1_mmr"],
        new_t2_mmr - match["team_2_mmr"],
    )


def _apply_match_2v2_resolution(
    self: TransitionManager,
    match_id: int,
    match: Matches2v2Row,
    result: str,
    t1_change: int,
    t2_change: int,
    new_t1_mmr: int,
    new_t2_mmr: int,
    now: datetime,
    *,
    team_1_report: str | None = None,
    team_1_reporter_discord_uid: int | None = None,
    team_2_report: str | None = None,
    team_2_reporter_discord_uid: int | None = None,
    admin_intervened: bool = False,
    admin_discord_uid: int | None = None,
) -> Matches2v2Row:
    """Write match result, update team MMRs, return all four players to
    ``in_party``, and return the updated match row."""
    t1_p1 = match["team_1_player_1_discord_uid"]
    t1_p2 = match["team_1_player_2_discord_uid"]
    t2_p1 = match["team_2_player_1_discord_uid"]
    t2_p2 = match["team_2_player_2_discord_uid"]

    # Compute MMR updates before any writes.
    t1_mmr_update = _compute_mmr_update_2v2(self, t1_p1, t1_p2, new_t1_mmr, now)
    t2_mmr_update = _compute_mmr_update_2v2(self, t2_p1, t2_p2, new_t2_mmr, now)

    # Write the match row.
    finalise_kwargs: dict = dict(
        match_result=result,
        team_1_report=team_1_report,
        team_1_reporter_discord_uid=team_1_reporter_discord_uid,
        team_2_report=team_2_report,
        team_2_reporter_discord_uid=team_2_reporter_discord_uid,
        team_1_mmr_change=t1_change if t1_change != 0 else None,
        team_2_mmr_change=t2_change if t2_change != 0 else None,
        completed_at=now,
    )
    self._db_writer.finalise_match_2v2(match_id, **finalise_kwargs)

    # Update MMR rows.
    mmr_updates = [u for u in (t1_mmr_update, t2_mmr_update) if u is not None]
    if mmr_updates:
        self._db_writer.batch_update_mmrs_2v2(mmr_updates)

    # Update in-memory cache.
    cache_kwargs: dict = {k: v for k, v in finalise_kwargs.items() if v is not None}
    _update_match_2v2_cache(self, match_id, **cache_kwargs)
    for u in mmr_updates:
        _apply_mmr_2v2_cache_update(
            self, u["player_1_discord_uid"], u["player_2_discord_uid"], u
        )

    # Return players to in_party if their party still exists, otherwise idle.
    for leader, member in ((t1_p1, t1_p2), (t2_p1, t2_p2)):
        party = self._state_manager.parties_2v2.get(leader)
        if party is not None and party["member_discord_uid"] == member:
            self._set_player_status(leader, "in_party", match_mode=None, match_id=None)
            self._set_player_status(member, "in_party", match_mode=None, match_id=None)
        else:
            logger.warning(
                f"Party for team ({leader}, {member}) no longer exists — "
                "returning players to idle"
            )
            self._set_player_status(leader, "idle", match_mode=None, match_id=None)
            self._set_player_status(member, "idle", match_mode=None, match_id=None)
    self._confirmations.pop(match_id, None)

    self.rebuild_leaderboard()

    updated = _get_match_2v2_row(self, match_id)
    if updated is None:
        raise RuntimeError(f"2v2 match #{match_id} not found after resolution")
    return updated


def _finalise_match_2v2(
    self: TransitionManager,
    match_id: int,
    match: Matches2v2Row,
    agreed_result: str,
) -> Matches2v2Row:
    now = utc_now()
    new_t1_mmr, new_t2_mmr, t1_change, t2_change = _calculate_mmr_changes_2v2(
        match, agreed_result
    )
    updated = _apply_match_2v2_resolution(
        self,
        match_id,
        match,
        agreed_result,
        t1_change,
        t2_change,
        new_t1_mmr,
        new_t2_mmr,
        now,
    )

    self._db_writer.insert_event(
        {
            "discord_uid": 1,
            "event_type": "match_event",
            "action": "match_completed",
            "game_mode": "2v2",
            "match_id": match_id,
            "event_data": {
                "game_mode": "2v2",
                "match_id": match_id,
                "result": agreed_result,
                "t1_mmr_change": t1_change,
                "t2_mmr_change": t2_change,
            },
        }
    )

    logger.info(
        f"2v2 match #{match_id} finalised: {agreed_result} "
        f"(t1 {match['team_1_mmr']}→{new_t1_mmr}, "
        f"t2 {match['team_2_mmr']}→{new_t2_mmr})"
    )
    return updated


def _handle_conflict_2v2(
    self: TransitionManager, match_id: int, match: Matches2v2Row
) -> Matches2v2Row:
    now = utc_now()
    updated = _apply_match_2v2_resolution(
        self,
        match_id,
        match,
        "conflict",
        0,
        0,
        match["team_1_mmr"],
        match["team_2_mmr"],
        now,
    )

    self._db_writer.insert_event(
        {
            "discord_uid": 1,
            "event_type": "match_event",
            "action": "match_conflict",
            "game_mode": "2v2",
            "match_id": match_id,
            "event_data": {
                "game_mode": "2v2",
                "match_id": match_id,
                "t1_report": match["team_1_report"],
                "t2_report": match["team_2_report"],
            },
        }
    )

    logger.info(f"2v2 match #{match_id} marked as conflict (conflicting reports)")
    return updated


# ==================================================================
# MMR helpers
# ==================================================================


def _compute_mmr_update_2v2(
    self: TransitionManager,
    p1_discord_uid: int,
    p2_discord_uid: int,
    new_mmr: int,
    now: datetime,
) -> dict | None:
    """Return a fully-populated mmrs_2v2 row dict, or None if no row exists.

    UIDs are normalized (smaller first) before lookup.
    """
    uid_lo = min(p1_discord_uid, p2_discord_uid)
    uid_hi = max(p1_discord_uid, p2_discord_uid)

    df = self._state_manager.mmrs_2v2_df
    rows = df.filter(
        (pl.col("player_1_discord_uid") == uid_lo)
        & (pl.col("player_2_discord_uid") == uid_hi)
    )
    if rows.is_empty():
        logger.warning(
            f"No mmrs_2v2 row for pair ({uid_lo}, {uid_hi}) — skipping MMR update"
        )
        return None

    current = rows.row(0, named=True)
    stats = count_game_stats_2v2(self._state_manager.matches_2v2_df, uid_lo, uid_hi)
    return {
        **current,
        "mmr": new_mmr,
        "games_played": stats["games_played"],
        "games_won": stats["games_won"],
        "games_lost": stats["games_lost"],
        "games_drawn": stats["games_drawn"],
        "last_played_at": now,
    }


def _apply_mmr_2v2_cache_update(
    self: TransitionManager,
    p1_discord_uid: int,
    p2_discord_uid: int,
    updated: dict,
) -> None:
    """Swap in a pre-computed mmrs_2v2 row in the in-memory cache."""
    uid_lo = min(p1_discord_uid, p2_discord_uid)
    uid_hi = max(p1_discord_uid, p2_discord_uid)
    df = self._state_manager.mmrs_2v2_df
    self._state_manager.mmrs_2v2_df = df.filter(
        ~(
            (pl.col("player_1_discord_uid") == uid_lo)
            & (pl.col("player_2_discord_uid") == uid_hi)
        )
    ).vstack(pl.DataFrame([updated]).cast(df.schema))


# ==================================================================
# Cache helpers
# ==================================================================


def _update_match_2v2_cache(
    self: TransitionManager, match_id: int, **updates: object
) -> None:
    """Patch specific columns on a cached matches_2v2 row."""
    df = self._state_manager.matches_2v2_df
    rows = df.filter(pl.col("id") == match_id)
    if rows.is_empty():
        return
    row = rows.row(0, named=True)
    row.update(updates)
    self._state_manager.matches_2v2_df = df.filter(pl.col("id") != match_id).vstack(
        pl.DataFrame([row]).cast(df.schema)
    )
