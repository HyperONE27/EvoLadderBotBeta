from datetime import datetime, timezone

import polars as pl
import structlog

from backend.algorithms.game_stats import count_game_stats
from backend.algorithms.match_params import resolve_match_params
from backend.algorithms.matchmaker import run_matchmaking_wave
from backend.algorithms.ratings_1v1 import get_default_mmr, get_new_ratings
from backend.core.config import CURRENT_SEASON
from backend.database.database import DatabaseWriter
from backend.domain_types.dataframes import Matches1v1Row
from backend.domain_types.ephemeral import (
    MatchCandidate1v1,
    MatchParams1v1,
    QueueEntry1v1,
)
from backend.orchestrator.state import StateManager

from common.lookups.country_lookups import get_country_by_code


logger = structlog.get_logger(__name__)


class TransitionManager:
    def __init__(self, state_manager: StateManager, db_writer: DatabaseWriter) -> None:
        self._state_manager = state_manager
        self._db_writer = db_writer
        # Track match confirmations: match_id → set of discord_uids
        self._confirmations: dict[int, set[int]] = {}

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
        self, discord_uid: int, discord_username: str, country_code: str
    ) -> tuple[bool, str | None]:
        player = self._handle_missing_player(discord_uid, discord_username)

        country = get_country_by_code(country_code)
        if country is None:
            return False, f"Country code {country_code!r} not found."

        player_id: int = player["id"]
        df: pl.DataFrame = self._state_manager.players_df
        self._db_writer.update_player_nationality(player_id, country_code)

        self._state_manager.players_df = df.with_columns(
            nationality=pl.when(pl.col("id") == player_id)
            .then(pl.lit(country_code))
            .otherwise(pl.col("nationality"))
        )

        logger.info(
            f"Successfully set country for player {discord_username} "
            f"to {country['name']} ({country_code})"
        )
        return True, f"Country successfully set to {country['name']}."

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

    def set_tos_for_player(
        self,
        discord_uid: int,
        discord_username: str,
        accepted: bool,
    ) -> tuple[bool, str | None]:
        player = self._handle_missing_player(discord_uid, discord_username)
        player_id: int = player["id"]
        accepted_tos_at = datetime.now(timezone.utc)

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

        verb = "accepted" if accepted else "declined"
        logger.info(
            f"Player {discord_username} ({discord_uid}) {verb} the terms of service"
        )
        return True, None

    # ==================================================================
    # Startup reset
    # ==================================================================

    def reset_all_player_statuses(self) -> None:
        """Reset all players to idle with no active match (called at startup)."""
        self._db_writer.reset_all_player_statuses()

        df = self._state_manager.players_df
        self._state_manager.players_df = df.with_columns(
            player_status=pl.lit("idle"),
            current_match_mode=pl.lit(None),
            current_match_id=pl.lit(None),
        )
        logger.info("Reset all player statuses to idle")

    # ==================================================================
    # Preferences 1v1
    # ==================================================================

    def upsert_preferences_1v1(
        self,
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

    # ==================================================================
    # MMR helpers
    # ==================================================================

    def _handle_missing_mmr_1v1(
        self, discord_uid: int, player_name: str, race: str
    ) -> dict:
        """Return the MMR row, creating it with default MMR if it doesn't exist."""
        df = self._state_manager.mmrs_1v1_df

        rows = df.filter(
            (pl.col("discord_uid") == discord_uid) & (pl.col("race") == race)
        )
        if not rows.is_empty():
            return rows.row(0, named=True)

        logger.info(
            f"Creating default MMR row for {player_name} ({discord_uid}), race={race}"
        )
        created = self._db_writer.add_mmr_1v1(
            discord_uid, player_name, race, get_default_mmr()
        )
        self._state_manager.mmrs_1v1_df = df.vstack(
            pl.DataFrame([created]).cast(df.schema)
        )
        return created

    # ==================================================================
    # Player status helpers
    # ==================================================================

    def _set_player_status(
        self,
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

    # ==================================================================
    # Queue 1v1
    # ==================================================================

    def join_queue_1v1(
        self,
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

        # Ensure MMR rows exist; use provided values if given, else look up/create.
        actual_bw_mmr: int | None = None
        actual_sc2_mmr: int | None = None

        if bw_race is not None:
            mmr_row = self._handle_missing_mmr_1v1(discord_uid, player_name, bw_race)
            actual_bw_mmr = bw_mmr if bw_mmr is not None else mmr_row["mmr"]

        if sc2_race is not None:
            mmr_row = self._handle_missing_mmr_1v1(discord_uid, player_name, sc2_race)
            actual_sc2_mmr = sc2_mmr if sc2_mmr is not None else mmr_row["mmr"]

        entry = QueueEntry1v1(
            discord_uid=discord_uid,
            player_name=player_name,
            bw_race=bw_race,
            sc2_race=sc2_race,
            bw_mmr=actual_bw_mmr,
            sc2_mmr=actual_sc2_mmr,
            map_vetoes=map_vetoes,
            joined_at=datetime.now(timezone.utc),
            wait_cycles=0,
        )
        self._state_manager.queue_1v1.append(entry)
        self._set_player_status(discord_uid, "queueing", match_mode="1v1")

        logger.info(f"Player {player_name} ({discord_uid}) joined the 1v1 queue")
        return True, None

    def leave_queue_1v1(self, discord_uid: int) -> tuple[bool, str | None]:
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
    # Matchmaking wave
    # ==================================================================

    def run_matchmaking_wave(
        self,
        queue_snapshot: list[QueueEntry1v1],
    ) -> list[Matches1v1Row]:
        """Run one matchmaking wave and create match rows for every pair found.

        1. Calls ``algorithms/matchmaker.run_matchmaking_wave`` (pure).
        2. For each candidate, calls ``algorithms/match_params.resolve_match_params`` (pure).
        3. Creates DB + cache rows for every match; updates player statuses;
           removes matched players from the queue.

        Returns the list of newly created ``Matches1v1Row`` dicts.
        """
        remaining, candidates = run_matchmaking_wave(queue_snapshot)

        # Replace the queue with unmatched players (wait_cycles already incremented).
        self._state_manager.queue_1v1 = remaining

        if not candidates:
            return []

        created_matches: list[Matches1v1Row] = []

        for candidate in candidates:
            try:
                match_row = self._create_match_from_candidate(candidate)
                created_matches.append(match_row)
            except Exception:
                logger.exception(
                    "Failed to create match for candidate "
                    f"{candidate['player_1_discord_uid']} vs "
                    f"{candidate['player_2_discord_uid']}"
                )

        logger.info(
            f"Matchmaking wave complete: {len(created_matches)} matches created, "
            f"{len(remaining)} players still in queue"
        )
        return created_matches

    def _create_match_from_candidate(
        self, candidate: MatchCandidate1v1
    ) -> Matches1v1Row:
        """Resolve parameters, write the match row, and update player states."""
        p1_uid = candidate["player_1_discord_uid"]
        p2_uid = candidate["player_2_discord_uid"]

        # Resolve locations — fall back to opponent's location if missing.
        p1_loc = self._get_player_location(p1_uid)
        p2_loc = self._get_player_location(p2_uid)

        if p1_loc is None and p2_loc is not None:
            p1_loc = p2_loc
        elif p2_loc is None and p1_loc is not None:
            p2_loc = p1_loc
        elif p1_loc is None and p2_loc is None:
            # Both missing — pick a sensible fallback.  The cross-table
            # requires valid region codes so we can't just pass None.
            p1_loc = "NAC"
            p2_loc = "NAC"

        # At this point both are guaranteed non-None by the if/elif chain.
        assert p1_loc is not None
        assert p2_loc is not None

        params: MatchParams1v1 = resolve_match_params(
            candidate,
            player_1_location=p1_loc,
            player_2_location=p2_loc,
            maps=self._state_manager.maps,
            cross_table=self._state_manager.cross_table,
            season=CURRENT_SEASON,
        )

        now = datetime.now(timezone.utc)

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

        logger.info(
            f"Match #{match_id} created: "
            f"{candidate['player_1_name']} vs {candidate['player_2_name']} "
            f"on {params['map_name']} @ {params['server_name']}"
        )

        return Matches1v1Row(**created)  # type: ignore[typeddict-item, no-any-return]

    def _get_player_location(self, discord_uid: int) -> str | None:
        df = self._state_manager.players_df
        rows = df.filter(pl.col("discord_uid") == discord_uid)
        if rows.is_empty():
            return None
        return rows.row(0, named=True).get("location")

    def _get_player_nationality(self, discord_uid: int) -> str | None:
        df = self._state_manager.players_df
        rows = df.filter(pl.col("discord_uid") == discord_uid)
        if rows.is_empty():
            return None
        return rows.row(0, named=True).get("nationality")

    def _get_player_letter_rank(self, discord_uid: int, race: str) -> str:
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

    # ==================================================================
    # Match confirmation
    # ==================================================================

    def confirm_match(self, match_id: int, discord_uid: int) -> tuple[bool, bool]:
        """Record that a player has confirmed a match.

        Returns ``(success, both_confirmed)``.
        """
        if match_id not in self._confirmations:
            self._confirmations[match_id] = set()

        self._confirmations[match_id].add(discord_uid)
        both = len(self._confirmations[match_id]) >= 2

        logger.info(
            f"Player {discord_uid} confirmed match #{match_id} (both_confirmed={both})"
        )
        return True, both

    def is_match_confirmed(self, match_id: int) -> bool:
        return len(self._confirmations.get(match_id, set())) >= 2

    # ==================================================================
    # Match abort
    # ==================================================================

    def abort_match(self, match_id: int, discord_uid: int) -> tuple[bool, str | None]:
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

        now = datetime.now(timezone.utc)

        self._db_writer.finalise_match_1v1(
            match_id,
            match_result="abort",
            player_1_report=p1_report,
            player_2_report=p2_report,
            completed_at=now,
        )

        self._update_match_cache(
            match_id,
            player_1_report=p1_report,
            player_2_report=p2_report,
            match_result="abort",
            completed_at=now,
        )

        self._set_player_status(p1_uid, "idle")
        self._set_player_status(p2_uid, "idle")
        self._confirmations.pop(match_id, None)

        logger.info(f"Match #{match_id} aborted by player {discord_uid}")
        return True, None

    # ==================================================================
    # Confirmation timeout (abandoned)
    # ==================================================================

    def handle_confirmation_timeout(self, match_id: int) -> tuple[bool, str | None]:
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

        now = datetime.now(timezone.utc)

        self._db_writer.finalise_match_1v1(
            match_id,
            match_result="abandoned",
            player_1_report=p1_report,
            player_2_report=p2_report,
            completed_at=now,
        )

        self._update_match_cache(
            match_id,
            player_1_report=p1_report,
            player_2_report=p2_report,
            match_result="abandoned",
            completed_at=now,
        )

        self._set_player_status(p1_uid, "idle")
        self._set_player_status(p2_uid, "idle")
        self._confirmations.pop(match_id, None)

        logger.info(f"Match #{match_id} abandoned (confirmation timeout)")
        return True, None

    # ==================================================================
    # Match result reporting
    # ==================================================================

    def report_match_result(
        self,
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
        assert match is not None

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
            finalised = self._finalise_match(match_id, match, p1_report)
            return True, None, finalised
        else:
            # Conflict — mark as conflict, no MMR changes.
            finalised = self._handle_conflict(match_id, match)
            return True, "Reports conflict — match marked as conflict.", finalised

    def _finalise_match(
        self,
        match_id: int,
        match: Matches1v1Row,
        agreed_result: str,
    ) -> Matches1v1Row:
        """Both players agree — calculate MMR, write everything, return to idle."""
        now = datetime.now(timezone.utc)

        # Map string result to the integer code that ratings_1v1 expects.
        result_code_map = {"player_1_win": 1, "player_2_win": 2, "draw": 0}
        result_code = result_code_map[agreed_result]

        new_p1_mmr, new_p2_mmr = get_new_ratings(
            match["player_1_mmr"], match["player_2_mmr"], result_code
        )
        p1_change = new_p1_mmr - match["player_1_mmr"]
        p2_change = new_p2_mmr - match["player_2_mmr"]

        p1_uid = match["player_1_discord_uid"]
        p2_uid = match["player_2_discord_uid"]
        p1_race = match["player_1_race"]
        p2_race = match["player_2_race"]

        # Compute new MMR rows before any writes.
        p1_mmr_update = self._compute_mmr_update(
            p1_uid, p1_race, new_p1_mmr, agreed_result, is_player_1=True, now=now
        )
        p2_mmr_update = self._compute_mmr_update(
            p2_uid, p2_race, new_p2_mmr, agreed_result, is_player_1=False, now=now
        )

        # Write match result (single UPDATE).
        self._db_writer.finalise_match_1v1(
            match_id,
            match_result=agreed_result,
            player_1_mmr_change=p1_change,
            player_2_mmr_change=p2_change,
            completed_at=now,
        )

        # Write both MMR rows in a single upsert.
        mmr_updates = [u for u in (p1_mmr_update, p2_mmr_update) if u is not None]
        if mmr_updates:
            self._db_writer.batch_update_mmrs_1v1(mmr_updates)

        # Update caches.
        self._update_match_cache(
            match_id,
            match_result=agreed_result,
            player_1_mmr_change=p1_change,
            player_2_mmr_change=p2_change,
            completed_at=now,
        )
        if p1_mmr_update is not None:
            self._apply_mmr_cache_update(p1_uid, p1_race, p1_mmr_update)
        if p2_mmr_update is not None:
            self._apply_mmr_cache_update(p2_uid, p2_race, p2_mmr_update)

        # Return both players to idle.
        self._set_player_status(p1_uid, "idle")
        self._set_player_status(p2_uid, "idle")
        self._confirmations.pop(match_id, None)

        logger.info(
            f"Match #{match_id} finalised: {agreed_result} "
            f"(p1 {match['player_1_mmr']}→{new_p1_mmr}, "
            f"p2 {match['player_2_mmr']}→{new_p2_mmr})"
        )

        updated_match = self._get_match_row(match_id)
        assert updated_match is not None
        return updated_match

    def _handle_conflict(self, match_id: int, match: Matches1v1Row) -> Matches1v1Row:
        """Reports disagree — mark as conflict, no MMR changes, return to idle."""
        now = datetime.now(timezone.utc)

        self._db_writer.finalise_match_1v1(
            match_id,
            match_result="conflict",
            player_1_mmr_change=0,
            player_2_mmr_change=0,
            completed_at=now,
        )

        self._update_match_cache(
            match_id,
            match_result="conflict",
            player_1_mmr_change=0,
            player_2_mmr_change=0,
            completed_at=now,
        )

        self._set_player_status(match["player_1_discord_uid"], "idle")
        self._set_player_status(match["player_2_discord_uid"], "idle")
        self._confirmations.pop(match_id, None)

        logger.info(f"Match #{match_id} marked as conflict (conflicting reports)")

        updated = self._get_match_row(match_id)
        assert updated is not None
        return updated

    def _compute_mmr_update(
        self,
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
        rows = df.filter(
            (pl.col("discord_uid") == discord_uid) & (pl.col("race") == race)
        )
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
        self, discord_uid: int, race: str, updated: dict
    ) -> None:
        """Swap in a pre-computed MMR row in the in-memory cache."""
        df = self._state_manager.mmrs_1v1_df
        self._state_manager.mmrs_1v1_df = df.filter(
            ~((pl.col("discord_uid") == discord_uid) & (pl.col("race") == race))
        ).vstack(pl.DataFrame([updated]).cast(df.schema))

    def _set_mmr_cache_value(self, discord_uid: int, race: str, mmr: int) -> None:
        """Set only the MMR value on an existing cache row (no stat changes)."""
        df = self._state_manager.mmrs_1v1_df
        rows = df.filter(
            (pl.col("discord_uid") == discord_uid) & (pl.col("race") == race)
        )
        if rows.is_empty():
            return
        updated = rows.row(0, named=True)
        updated["mmr"] = mmr
        self._state_manager.mmrs_1v1_df = df.filter(
            ~((pl.col("discord_uid") == discord_uid) & (pl.col("race") == race))
        ).vstack(pl.DataFrame([updated]).cast(df.schema))

    def _recalculate_game_stats(self, discord_uid: int, race: str) -> None:
        """Recalculate games_played/won/lost/drawn from matches_1v1 ground truth
        and write to both DB and in-memory cache."""
        df = self._state_manager.mmrs_1v1_df
        rows = df.filter(
            (pl.col("discord_uid") == discord_uid) & (pl.col("race") == race)
        )
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

    # ==================================================================
    # Cache helpers
    # ==================================================================

    def _get_match_row(self, match_id: int) -> Matches1v1Row | None:
        df = self._state_manager.matches_1v1_df
        rows = df.filter(pl.col("id") == match_id)
        if rows.is_empty():
            return None
        return Matches1v1Row(**rows.row(0, named=True))  # type: ignore[typeddict-item, no-any-return]

    def _update_match_cache(self, match_id: int, **updates: object) -> None:
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

    # ==================================================================
    # Replay 1v1
    # ==================================================================

    def insert_replay_1v1_pending(
        self,
        match_id: int,
        discord_uid: int,
        parsed: dict,
        initial_path: str,
        uploaded_at: datetime,
    ) -> dict:
        """
        Insert a replay row with ``upload_status='pending'`` and return the
        created row (which contains the DB-assigned ``id``).

        Write-through: DB is written first, then the in-memory cache is updated.
        """
        data = {
            "matches_1v1_id": match_id,
            "replay_path": initial_path,
            "replay_hash": parsed["replay_hash"],
            "replay_time": parsed["replay_time"],
            "uploaded_at": uploaded_at.isoformat(),
            "player_1_name": parsed["player_1_name"],
            "player_2_name": parsed["player_2_name"],
            "player_1_race": parsed["player_1_race"],
            "player_2_race": parsed["player_2_race"],
            "match_result": parsed["match_result"],
            "player_1_handle": parsed["player_1_handle"],
            "player_2_handle": parsed["player_2_handle"],
            "observers": parsed["observers"],
            "map_name": parsed["map_name"],
            "game_duration_seconds": parsed["game_duration_seconds"],
            "game_privacy": parsed["game_privacy"],
            "game_speed": parsed["game_speed"],
            "game_duration_setting": parsed["game_duration_setting"],
            "locked_alliances": parsed["locked_alliances"],
            "cache_handles": parsed["cache_handles"],
            "upload_status": "pending",
        }

        # DB write first (write-through).
        created = self._db_writer.add_replay_1v1(data)

        # Update in-memory cache.
        df = self._state_manager.replays_1v1_df
        self._state_manager.replays_1v1_df = df.vstack(
            pl.DataFrame([created]).cast(df.schema)
        )

        return created

    def update_replay_status(
        self,
        replay_id: int,
        status: str,
        final_path: str | None = None,
    ) -> None:
        """
        Update ``upload_status`` for a replay row.  If *final_path* is given,
        also update ``replay_path`` (used when changing from the initial
        placeholder to the Supabase public URL).

        Write-through: DB is written first, then the in-memory cache is updated.
        """
        # DB write first.
        self._db_writer.update_replay_1v1_status(replay_id, status, final_path)

        # Update in-memory cache by swapping the row.
        df = self._state_manager.replays_1v1_df
        rows = df.filter(pl.col("id") == replay_id)
        if rows.is_empty():
            return

        row = rows.row(0, named=True)
        row["upload_status"] = status
        if final_path is not None:
            row["replay_path"] = final_path

        self._state_manager.replays_1v1_df = df.filter(
            pl.col("id") != replay_id
        ).vstack(pl.DataFrame([row]).cast(df.schema))

    def update_match_replay_refs(
        self,
        match_id: int,
        player_num: int,
        replay_path: str,
        replay_row_id: int,
        uploaded_at: datetime,
    ) -> None:
        """
        Update a match row with the latest replay path, replay row ID, and
        upload timestamp for the given player number (1 or 2).

        Write-through: DB is written first, then the in-memory cache is updated.
        """
        # DB write first.
        self._db_writer.update_match_1v1_replay(
            match_id, player_num, replay_path, replay_row_id, uploaded_at
        )

        # Update in-memory cache using the generic row-swap helper.
        self._update_match_cache(
            match_id,
            **{
                f"player_{player_num}_replay_path": replay_path,
                f"player_{player_num}_replay_row_id": replay_row_id,
                f"player_{player_num}_uploaded_at": uploaded_at,
            },
        )

    # ==================================================================
    # Admin: status reset
    # ==================================================================

    def reset_player_status(
        self, discord_uid: int
    ) -> tuple[bool, str | None, str | None]:
        """Reset a player's status to idle, clearing match mode and match ID.

        Returns ``(success, error_message, old_status)``.
        """
        df = self._state_manager.players_df
        rows = df.filter(pl.col("discord_uid") == discord_uid)
        if rows.is_empty():
            return False, "Player not found.", None

        row = rows.row(0, named=True)
        old_status: str = row.get("player_status") or "unknown"

        if old_status == "idle" and row.get("current_match_id") is None:
            return False, "Player is already idle with no active match.", old_status

        self._set_player_status(discord_uid, "idle", match_mode=None, match_id=None)

        logger.info(
            f"Admin reset player {discord_uid} status from {old_status!r} to idle"
        )
        return True, None, old_status

    # ==================================================================
    # Admin: ban toggle
    # ==================================================================

    def toggle_ban(self, discord_uid: int) -> tuple[bool, bool]:
        """Toggle is_banned for a player. Returns (success, new_is_banned)."""
        df = self._state_manager.players_df
        rows = df.filter(pl.col("discord_uid") == discord_uid)
        if rows.is_empty():
            return False, False

        player = rows.row(0, named=True)
        player_id: int = player["id"]
        new_banned = not player["is_banned"]

        self._db_writer.update_player_ban_status(player_id, new_banned)

        self._state_manager.players_df = df.with_columns(
            is_banned=pl.when(pl.col("discord_uid") == discord_uid)
            .then(pl.lit(new_banned))
            .otherwise(pl.col("is_banned"))
        )

        logger.info(f"Player {discord_uid} ban toggled to {new_banned}")
        return True, new_banned

    # ==================================================================
    # Admin: resolve match
    # ==================================================================

    def admin_resolve_match(
        self,
        match_id: int,
        result: str,
        admin_discord_uid: int,
    ) -> dict:
        """Admin-resolve a match. Bypasses the two-report flow.

        Sets match_result, calculates MMR from snapshotted initial MMRs,
        sets admin_intervened=True, and returns both players to idle.

        Does NOT modify player_1_report or player_2_report.

        Args:
            match_id: Match to resolve.
            result: One of 'player_1_win', 'player_2_win', 'draw', 'invalidated'.
            admin_discord_uid: UID of the resolving admin.

        Returns:
            Dict with resolution details (match data, MMR changes, player info).
        """
        match = self._get_match_row(match_id)
        if match is None:
            return {"success": False, "error": "Match not found."}

        p1_uid = match["player_1_discord_uid"]
        p2_uid = match["player_2_discord_uid"]
        p1_mmr = match["player_1_mmr"]
        p2_mmr = match["player_2_mmr"]

        now = datetime.now(timezone.utc)

        # Calculate MMR changes from snapshotted initial MMRs.
        if result == "invalidated":
            p1_change = 0
            p2_change = 0
            new_p1_mmr = p1_mmr
            new_p2_mmr = p2_mmr
        else:
            result_code_map = {"player_1_win": 1, "player_2_win": 2, "draw": 0}
            result_code = result_code_map[result]
            new_p1_mmr, new_p2_mmr = get_new_ratings(p1_mmr, p2_mmr, result_code)
            p1_change = new_p1_mmr - p1_mmr
            p2_change = new_p2_mmr - p2_mmr

        # Write match resolution to DB.
        self._db_writer.admin_resolve_match_1v1(
            match_id,
            match_result=result,
            player_1_mmr_change=p1_change,
            player_2_mmr_change=p2_change,
            admin_discord_uid=admin_discord_uid,
            completed_at=now,
        )

        # Update match cache.
        self._update_match_cache(
            match_id,
            match_result=result,
            player_1_mmr_change=p1_change,
            player_2_mmr_change=p2_change,
            admin_intervened=True,
            admin_discord_uid=admin_discord_uid,
            completed_at=now,
        )

        # Apply MMR changes.
        p1_race = match["player_1_race"]
        p2_race = match["player_2_race"]

        if result == "invalidated":
            # Explicitly reset MMR to the snapshotted value from the match row.
            # This reverses any drift if the player's MMR changed during the match.
            self._db_writer.set_mmr_1v1_value(p1_uid, p1_race, p1_mmr)
            self._db_writer.set_mmr_1v1_value(p2_uid, p2_race, p2_mmr)
            self._set_mmr_cache_value(p1_uid, p1_race, p1_mmr)
            self._set_mmr_cache_value(p2_uid, p2_race, p2_mmr)

            # Recalculate game stats from ground truth (the match we just
            # invalidated no longer counts).
            self._recalculate_game_stats(p1_uid, p1_race)
            self._recalculate_game_stats(p2_uid, p2_race)
        else:
            p1_mmr_update = self._compute_mmr_update(
                p1_uid, p1_race, new_p1_mmr, result, is_player_1=True, now=now
            )
            p2_mmr_update = self._compute_mmr_update(
                p2_uid, p2_race, new_p2_mmr, result, is_player_1=False, now=now
            )

            mmr_updates = [u for u in (p1_mmr_update, p2_mmr_update) if u is not None]
            if mmr_updates:
                self._db_writer.batch_update_mmrs_1v1(mmr_updates)
            if p1_mmr_update is not None:
                self._apply_mmr_cache_update(p1_uid, p1_race, p1_mmr_update)
            if p2_mmr_update is not None:
                self._apply_mmr_cache_update(p2_uid, p2_race, p2_mmr_update)

        # Return both players to idle.
        self._set_player_status(p1_uid, "idle")
        self._set_player_status(p2_uid, "idle")
        self._confirmations.pop(match_id, None)

        logger.info(
            f"Match #{match_id} admin-resolved by {admin_discord_uid}: "
            f"{result} (p1 {p1_mmr}→{new_p1_mmr}, p2 {p2_mmr}→{new_p2_mmr})"
        )

        return {
            "success": True,
            "match_id": match_id,
            "result": result,
            "player_1_discord_uid": p1_uid,
            "player_2_discord_uid": p2_uid,
            "player_1_name": match["player_1_name"],
            "player_2_name": match["player_2_name"],
            "player_1_race": match["player_1_race"],
            "player_2_race": match["player_2_race"],
            "player_1_nationality": self._get_player_nationality(p1_uid),
            "player_2_nationality": self._get_player_nationality(p2_uid),
            "player_1_letter_rank": self._get_player_letter_rank(p1_uid, p1_race),
            "player_2_letter_rank": self._get_player_letter_rank(p2_uid, p2_race),
            "player_1_mmr": p1_mmr,
            "player_2_mmr": p2_mmr,
            "player_1_mmr_new": new_p1_mmr,
            "player_2_mmr_new": new_p2_mmr,
            "player_1_mmr_change": p1_change,
            "player_2_mmr_change": p2_change,
            "map_name": match["map_name"],
            "server_name": match["server_name"],
        }

    # ==================================================================
    # Admin: set MMR (idempotent)
    # ==================================================================

    def admin_set_mmr(
        self, discord_uid: int, race: str, new_mmr: int
    ) -> tuple[bool, int | None]:
        """Idempotent SET of a player's MMR. Returns (success, old_mmr)."""
        df = self._state_manager.mmrs_1v1_df
        rows = df.filter(
            (pl.col("discord_uid") == discord_uid) & (pl.col("race") == race)
        )
        if rows.is_empty():
            return False, None

        old_mmr: int = rows.row(0, named=True)["mmr"]

        # DB write.
        self._db_writer.set_mmr_1v1_value(discord_uid, race, new_mmr)

        # Cache update.
        self._state_manager.mmrs_1v1_df = df.with_columns(
            mmr=pl.when(
                (pl.col("discord_uid") == discord_uid) & (pl.col("race") == race)
            )
            .then(pl.lit(new_mmr, dtype=pl.Int16))
            .otherwise(pl.col("mmr"))
        )

        logger.info(f"Admin set MMR for {discord_uid}/{race}: {old_mmr} → {new_mmr}")
        return True, old_mmr

    # ==================================================================
    # Owner: toggle admin role
    # ==================================================================

    def toggle_admin_role(self, discord_uid: int, discord_username: str) -> dict:
        """Toggle a user between admin and inactive. Returns result dict.

        - New user → insert with role='admin'.
        - Existing 'inactive' → set role='admin', update last_promoted_at.
        - Existing 'admin' → set role='inactive', update last_demoted_at.
        - Existing 'owner' → refuse.
        """
        df = self._state_manager.admins_df
        rows = df.filter(pl.col("discord_uid") == discord_uid)
        now = datetime.now(timezone.utc)

        if rows.is_empty():
            # New admin — insert.
            created = self._db_writer.upsert_admin(
                discord_uid=discord_uid,
                discord_username=discord_username,
                role="admin",
                first_promoted_at=now,
                last_promoted_at=now,
            )
            self._state_manager.admins_df = df.vstack(
                pl.DataFrame([created]).cast(df.schema)
            )
            logger.info(f"New admin added: {discord_username} ({discord_uid})")
            return {"success": True, "action": "promoted", "new_role": "admin"}

        current = rows.row(0, named=True)
        current_role: str = current["role"]

        if current_role == "owner":
            return {"success": False, "error": "Cannot modify owner status."}

        if current_role == "admin":
            # Demote to inactive.
            self._db_writer.update_admin_role(
                discord_uid, "inactive", last_demoted_at=now
            )
            updated = {**current, "role": "inactive", "last_demoted_at": now}
            self._state_manager.admins_df = df.filter(
                pl.col("discord_uid") != discord_uid
            ).vstack(pl.DataFrame([updated]).cast(df.schema))
            logger.info(f"Admin demoted: {discord_username} ({discord_uid})")
            return {"success": True, "action": "demoted", "new_role": "inactive"}

        # inactive → promote back.
        self._db_writer.update_admin_role(discord_uid, "admin", last_promoted_at=now)
        updated = {**current, "role": "admin", "last_promoted_at": now}
        self._state_manager.admins_df = df.filter(
            pl.col("discord_uid") != discord_uid
        ).vstack(pl.DataFrame([updated]).cast(df.schema))
        logger.info(f"Admin re-promoted: {discord_username} ({discord_uid})")
        return {"success": True, "action": "promoted", "new_role": "admin"}

    # ==================================================================
    # Admin: snapshot helpers
    # ==================================================================

    def get_queue_snapshot_1v1(self) -> list[QueueEntry1v1]:
        """Return the current 1v1 queue (shallow copy)."""
        return list(self._state_manager.queue_1v1)

    def get_active_matches_1v1(self) -> list[Matches1v1Row]:
        """Return all matches with match_result IS NULL."""
        df = self._state_manager.matches_1v1_df
        active = df.filter(pl.col("match_result").is_null())
        return [
            Matches1v1Row(**row)  # type: ignore[typeddict-item]
            for row in active.iter_rows(named=True)
        ]
