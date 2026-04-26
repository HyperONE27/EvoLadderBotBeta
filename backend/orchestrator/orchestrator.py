from datetime import datetime, timedelta
from typing import Any

import polars as pl

from backend.algorithms.queue_join_analytics import (
    bucket_queue_join_counts,
    dedupe_per_fixed_window,
)
from backend.core.config import (
    ACTIVITY_QUEUE_JOIN_CHART_BUCKET_MINUTES,
    ACTIVITY_QUEUE_JOIN_DEDUPE_WINDOW_MINUTES,
)
from backend.database.database import DatabaseReader, DatabaseWriter
from backend.domain_types.dataframes import (
    Matches2v2Row,
    AdminsRow,
    ContentCreatorsRow,
    Matches1v1Row,
    MMRs1v1Row,
    NotificationsRow,
    PlayersRow,
    Preferences1v1Row,
    Preferences2v2Row,
)
from backend.domain_types.ephemeral import (
    LeaderboardEntry1v1,
    LeaderboardEntry2v2,
    PartyEntry2v2,
    PendingPartyInvite2v2,
    QueueEntry1v1,
    QueueEntry2v2,
)
from backend.orchestrator.queue_notify import compute_queue_activity_targets
from backend.orchestrator.reader import StateReader
from backend.orchestrator.state import StateManager
from backend.orchestrator.transitions import TransitionManager
from common.datetime_helpers import ensure_utc, utc_now


class Orchestrator:
    def __init__(self, state_manager: StateManager, db_writer: DatabaseWriter) -> None:
        self._state_manager = state_manager
        self._state_reader = StateReader(state_manager)
        self._transition_manager = TransitionManager(state_manager, db_writer)

    # ------------------------------------------------------------------
    # Reads — Admins
    # ------------------------------------------------------------------

    def get_admin(self, discord_uid: int) -> AdminsRow | None:
        """Get an admin by their Discord UID."""
        return self._state_reader.get_admin(discord_uid)

    # ------------------------------------------------------------------
    # Reads — Content creators
    # ------------------------------------------------------------------

    def get_content_creator(self, discord_uid: int) -> ContentCreatorsRow | None:
        """Get a content_creator row by Discord UID."""
        return self._state_reader.get_content_creator(discord_uid)

    def is_content_creator(self, discord_uid: int) -> bool:
        """True if the Discord UID is listed in content_creators."""
        return self._state_reader.is_content_creator(discord_uid)

    # ------------------------------------------------------------------
    # Writes — Content creators
    # ------------------------------------------------------------------

    def add_content_creator(self, discord_uid: int, discord_username: str) -> dict:
        """Add a content creator (idempotent). Returns a result dict."""
        return self._transition_manager.add_content_creator(
            discord_uid, discord_username
        )

    def remove_content_creator(self, discord_uid: int) -> dict:
        """Remove a content creator (idempotent). Returns a result dict."""
        return self._transition_manager.remove_content_creator(discord_uid)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_match_1v1(self, match_id: int) -> Matches1v1Row | None:
        """Get a 1v1 match by its ID."""
        return self._state_reader.get_match_1v1(match_id)

    def get_match_2v2(self, match_id: int) -> Matches2v2Row | None:
        """Get a 2v2 match by its ID."""
        from backend.orchestrator.transitions._match_2v2 import _get_match_2v2_row

        return _get_match_2v2_row(self._transition_manager, match_id)

    def get_mmr_1v1(self, discord_uid: int, race: str) -> MMRs1v1Row | None:
        """Get a 1v1 MMR for a player by their Discord UID and race."""
        return self._state_reader.get_mmr_1v1(discord_uid, race)

    def get_mmrs_1v1(self, discord_uid: int) -> list[MMRs1v1Row]:
        """Get all 1v1 MMRs for a player by their Discord UID."""
        return self._state_reader.get_all_mmrs_1v1(discord_uid)

    def get_player(self, discord_uid: int) -> PlayersRow | None:
        """Get a player by their Discord UID."""
        return self._state_reader.get_player(discord_uid)

    def get_player_by_string(self, s: str) -> PlayersRow | None:
        """Resolve an arbitrary string to a player row (UID, player_name, or discord_username)."""
        return self._state_reader.get_player_by_string(s)

    def is_player_name_available(
        self, player_name: str, exclude_discord_uid: int | None = None
    ) -> bool:
        """True if no other player row uses this exact player_name."""
        return self._state_reader.is_player_name_available(
            player_name, exclude_discord_uid
        )

    def submit_referral(
        self, referee_discord_uid: int, referral_code: str
    ) -> tuple[bool, str | None]:
        """Validate and record a referral. Returns (success, referrer_player_name_or_error)."""
        return self._transition_manager.submit_referral(
            referee_discord_uid, referral_code
        )

    def get_referral_count(self, discord_uid: int, has_played: bool = True) -> int:
        """Count players referred by discord_uid (optionally requiring at least one game played)."""
        return self._state_reader.get_referral_count(discord_uid, has_played)

    def get_active_player_count(self) -> int:
        """Count unique players who have played at least one game across 1v1 or 2v2."""
        return self._state_reader.get_active_player_count()

    def get_preferences_1v1(self, discord_uid: int) -> Preferences1v1Row | None:
        """Get a player's 1v1 preferences by their Discord UID."""
        return self._state_reader.get_preferences_1v1(discord_uid)

    def get_preferences_2v2(self, discord_uid: int) -> Preferences2v2Row | None:
        """Get a player's 2v2 preferences by their Discord UID."""
        return self._state_reader.get_preferences_2v2(discord_uid)

    def get_profile(
        self, discord_uid: int
    ) -> tuple[
        PlayersRow | None,
        list[dict[str, Any]],
        list[dict[str, Any]],
        NotificationsRow | None,
    ]:
        """Get a player's profile: player row, enriched 1v1 MMRs, top-5 2v2 partners, notifications."""

        player = self._state_reader.get_player(discord_uid)
        mmrs_1v1 = self._state_reader.build_profile_mmrs_1v1(discord_uid)
        mmrs_2v2 = self._state_reader.build_profile_2v2_partners(discord_uid)
        notifications = self._state_reader.get_notifications_row(discord_uid)
        return player, mmrs_1v1, mmrs_2v2, notifications

    def get_active_matches_snapshot_1v1(self) -> list[dict[str, Any]]:
        """Active 1v1 matches with letter ranks and ISO nationalities for /snapshot."""

        raw = self._transition_manager.get_active_matches_1v1()
        return [self._state_reader.enrich_match_for_snapshot(m) for m in raw]

    def get_active_matches_snapshot_2v2(self) -> list[dict[str, Any]]:
        """Active 2v2 matches with team letter ranks and player nationalities for /snapshot."""
        raw = self._transition_manager.get_active_matches_2v2()
        return [self._state_reader.enrich_match_for_snapshot_2v2(m) for m in raw]

    def get_queue_1v1(self) -> list[QueueEntry1v1]:
        """Return the current 1v1 queue (shallow copy)."""
        return self._state_reader.get_queue_1v1()

    def get_queue_entry_1v1(self, discord_uid: int) -> QueueEntry1v1 | None:
        """Find a specific player's queue entry, or None."""
        return self._state_reader.get_queue_entry_1v1(discord_uid)

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    def upsert_preferences_1v1(
        self,
        discord_uid: int,
        last_chosen_races: list[str],
        last_chosen_vetoes: list[str],
    ) -> None:
        """Create or update a player's 1v1 queue preferences."""
        self._transition_manager.upsert_preferences_1v1(
            discord_uid, last_chosen_races, last_chosen_vetoes
        )

    def upsert_preferences_2v2(
        self,
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
        self._transition_manager.upsert_preferences_2v2(
            discord_uid,
            last_pure_bw_leader_race,
            last_pure_bw_member_race,
            last_mixed_leader_race,
            last_mixed_member_race,
            last_pure_sc2_leader_race,
            last_pure_sc2_member_race,
            last_chosen_vetoes,
        )

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def reset_all_player_statuses(self) -> None:
        """Reset all players to idle (called at backend startup)."""
        self._transition_manager.reset_all_player_statuses()

    # ------------------------------------------------------------------
    # Queue stats
    # ------------------------------------------------------------------

    def get_queue_stats(self) -> dict[str, int]:
        """Return queue population stats for the searching embed."""
        queue = self._state_reader.get_queue_1v1()
        bw_only = 0
        sc2_only = 0
        both = 0
        for entry in queue:
            has_bw = entry["bw_race"] is not None
            has_sc2 = entry["sc2_race"] is not None
            if has_bw and has_sc2:
                both += 1
            elif has_bw:
                bw_only += 1
            elif has_sc2:
                sc2_only += 1
        return {
            "total": len(queue),
            "bw_only": bw_only,
            "sc2_only": sc2_only,
            "both": both,
            "active_matches": len(self._transition_manager.get_active_matches_1v1()),
        }

    def get_queue_stats_2v2(self) -> dict[str, int]:
        """Return 2v2 queue population by composition category."""
        queue = self._state_reader.get_queue_2v2()
        bw_only = 0
        mixed_only = 0
        sc2_only = 0
        bw_mixed = 0
        bw_sc2 = 0
        mixed_sc2 = 0
        all_three = 0
        for entry in queue:
            has_bw = (
                entry["pure_bw_leader_race"] is not None
                and entry["pure_bw_member_race"] is not None
            )
            has_mixed = (
                entry["mixed_leader_race"] is not None
                and entry["mixed_member_race"] is not None
            )
            has_sc2 = (
                entry["pure_sc2_leader_race"] is not None
                and entry["pure_sc2_member_race"] is not None
            )
            if has_bw and has_mixed and has_sc2:
                all_three += 1
            elif has_bw and has_mixed:
                bw_mixed += 1
            elif has_bw and has_sc2:
                bw_sc2 += 1
            elif has_mixed and has_sc2:
                mixed_sc2 += 1
            elif has_bw:
                bw_only += 1
            elif has_mixed:
                mixed_only += 1
            elif has_sc2:
                sc2_only += 1
        return {
            "total": len(queue),
            "bw_only": bw_only,
            "mixed_only": mixed_only,
            "sc2_only": sc2_only,
            "bw_mixed": bw_mixed,
            "bw_sc2": bw_sc2,
            "mixed_sc2": mixed_sc2,
            "all_three": all_three,
            "active_matches": len(self._transition_manager.get_active_matches_2v2()),
        }

    def get_activity_stats(self) -> dict[str, Any]:
        """Glanceable queue/match counts for the activity-status embed."""
        queue_1v1 = self._state_reader.get_queue_1v1()
        queue_2v2 = self._state_reader.get_queue_2v2()

        active_1v1 = self._transition_manager.get_active_matches_1v1()
        active_2v2 = self._transition_manager.get_active_matches_2v2()

        reader = DatabaseReader()
        last_queue_join_at_1v1 = reader.fetch_last_queue_join_at("1v1")
        last_queue_join_at_2v2 = reader.fetch_last_queue_join_at("2v2")

        now = utc_now()
        one_hour_ago = now - timedelta(hours=1)

        def _recent_matches(df: pl.DataFrame) -> int:
            if df.is_empty():
                return 0
            return df.filter(pl.col("assigned_at") >= one_hour_ago).height

        matches_last_hour_1v1 = _recent_matches(self._state_manager.matches_1v1_df)
        matches_last_hour_2v2 = _recent_matches(self._state_manager.matches_2v2_df)

        def _last_match_at(df: pl.DataFrame) -> datetime | None:
            if df.is_empty():
                return None
            ts = df.select(pl.col("assigned_at").max()).item()
            return ensure_utc(ts)

        last_match_at_1v1 = _last_match_at(self._state_manager.matches_1v1_df)
        last_match_at_2v2 = _last_match_at(self._state_manager.matches_2v2_df)

        queue_joins_last_hour_1v1 = len(
            self.fetch_deduped_queue_joins(one_hour_ago, now, "1v1")
        )
        queue_joins_last_hour_2v2 = len(
            self.fetch_deduped_queue_joins(one_hour_ago, now, "2v2")
        )

        return {
            "queue_1v1_count": len(queue_1v1),
            "queue_2v2_count": len(queue_2v2),
            "active_match_count_1v1": len(active_1v1),
            "active_match_count_2v2": len(active_2v2),
            "last_queue_join_at_1v1": last_queue_join_at_1v1,
            "last_queue_join_at_2v2": last_queue_join_at_2v2,
            "last_match_at_1v1": last_match_at_1v1,
            "last_match_at_2v2": last_match_at_2v2,
            "queue_joins_last_hour_1v1": queue_joins_last_hour_1v1,
            "queue_joins_last_hour_2v2": queue_joins_last_hour_2v2,
            "matches_last_hour_1v1": matches_last_hour_1v1,
            "matches_last_hour_2v2": matches_last_hour_2v2,
        }

    # ------------------------------------------------------------------
    # Player management
    # ------------------------------------------------------------------

    def register_player(
        self, discord_uid: int, discord_username: str
    ) -> tuple[bool, bool]:
        """Ensure a player row exists. Returns ``(was_created, completed_setup)``."""
        return self._transition_manager.register_player(discord_uid, discord_username)

    def toggle_lobby_guide(self, discord_uid: int) -> tuple[bool, bool]:
        """Toggle read_lobby_guide for a player. Returns (success, new_value)."""
        return self._transition_manager.toggle_lobby_guide(discord_uid)

    def setcountry(
        self, discord_uid: int, discord_username: str, country_code: str
    ) -> tuple[bool, str | None]:
        """Set the country for a player."""
        return self._transition_manager.set_country_for_player(
            discord_uid, discord_username, country_code
        )

    def set_tos(
        self,
        discord_uid: int,
        discord_username: str,
        accepted: bool,
    ) -> tuple[bool, str | None]:
        """Upsert a player's TOS acceptance and record the UTC timestamp."""
        return self._transition_manager.set_tos_for_player(
            discord_uid, discord_username, accepted
        )

    def setup(
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
        """Upsert a player's setup information."""
        return self._transition_manager.setup_player(
            discord_uid,
            discord_username,
            player_name,
            alt_player_names,
            battletag,
            nationality_code,
            location_code,
            language_code,
        )

    # ------------------------------------------------------------------
    # Party 2v2
    # ------------------------------------------------------------------

    def create_party_invite(
        self,
        inviter_discord_uid: int,
        inviter_player_name: str,
        invitee_discord_uid: int,
        invitee_player_name: str,
    ) -> tuple[bool, str | None]:
        """Create a pending party invite."""
        return self._transition_manager.create_party_invite(
            inviter_discord_uid,
            inviter_player_name,
            invitee_discord_uid,
            invitee_player_name,
        )

    def respond_to_party_invite(
        self,
        invitee_discord_uid: int,
        accepted: bool,
    ) -> tuple[bool, str | None, PendingPartyInvite2v2 | None]:
        """Accept or decline a party invite."""
        return self._transition_manager.respond_to_party_invite(
            invitee_discord_uid, accepted
        )

    def leave_party(self, discord_uid: int) -> tuple[bool, str | None, int | None]:
        """Leave the current party. Returns (success, error, partner_uid)."""
        return self._transition_manager.leave_party(discord_uid)

    def get_party(self, discord_uid: int) -> PartyEntry2v2 | None:
        """Return the party this player belongs to, or None."""
        return self._transition_manager.get_party(discord_uid)

    # ------------------------------------------------------------------
    # Queue 1v1
    # ------------------------------------------------------------------

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
        """Add a player to the 1v1 queue."""
        return self._transition_manager.join_queue_1v1(
            discord_uid,
            discord_username,
            bw_race,
            sc2_race,
            bw_mmr,
            sc2_mmr,
            map_vetoes,
        )

    def leave_queue_1v1(self, discord_uid: int) -> tuple[bool, str | None]:
        """Remove a player from the 1v1 queue."""
        return self._transition_manager.leave_queue_1v1(discord_uid)

    # ------------------------------------------------------------------
    # Queue 2v2
    # ------------------------------------------------------------------

    def join_queue_2v2(
        self,
        discord_uid: int,
        discord_username: str,
        pure_bw_leader_race: str | None,
        pure_bw_member_race: str | None,
        mixed_leader_race: str | None,
        mixed_member_race: str | None,
        pure_sc2_leader_race: str | None,
        pure_sc2_member_race: str | None,
        map_vetoes: list[str],
    ) -> tuple[bool, str | None]:
        """Add a party to the 2v2 queue.  Caller must be the party leader."""
        return self._transition_manager.join_queue_2v2(
            discord_uid,
            discord_username,
            pure_bw_leader_race,
            pure_bw_member_race,
            mixed_leader_race,
            mixed_member_race,
            pure_sc2_leader_race,
            pure_sc2_member_race,
            map_vetoes,
        )

    def leave_queue_2v2(self, discord_uid: int) -> tuple[bool, str | None]:
        """Remove a party from the 2v2 queue.  Caller must be the party leader."""
        return self._transition_manager.leave_queue_2v2(discord_uid)

    # ------------------------------------------------------------------
    # Matchmaking
    # ------------------------------------------------------------------

    def run_matchmaking_wave(self) -> list[Matches1v1Row]:
        """Run one matchmaking wave using the current queue snapshot."""
        queue_snapshot = self._state_reader.get_queue_1v1()
        return self._transition_manager.run_matchmaking_wave(queue_snapshot)

    def run_matchmaking_wave_2v2(self) -> list[Matches2v2Row]:
        """Run one 2v2 matchmaking wave using the current queue snapshot."""
        queue_snapshot = self._state_reader.get_queue_2v2()
        return self._transition_manager.run_matchmaking_wave_2v2(queue_snapshot)

    def confirm_match_2v2(self, match_id: int, discord_uid: int) -> tuple[bool, bool]:
        """Record that a player confirmed a 2v2 match. Returns (success, all_confirmed)."""
        return self._transition_manager.confirm_match_2v2(match_id, discord_uid)

    def is_match_2v2_confirmed(self, match_id: int) -> bool:
        """Check whether all four players have confirmed a 2v2 match."""
        return self._transition_manager.is_match_2v2_confirmed(match_id)

    def abort_match_2v2(
        self, match_id: int, discord_uid: int
    ) -> tuple[bool, str | None]:
        return self._transition_manager.abort_match_2v2(match_id, discord_uid)

    def handle_confirmation_timeout_2v2(self, match_id: int) -> tuple[bool, str | None]:
        return self._transition_manager.handle_confirmation_timeout_2v2(match_id)

    def report_match_result_2v2(
        self, match_id: int, discord_uid: int, report: str
    ) -> tuple[bool, str | None, Matches2v2Row | None]:
        return self._transition_manager.report_match_result_2v2(
            match_id, discord_uid, report
        )

    # ------------------------------------------------------------------
    # Match confirmation / abort / reporting
    # ------------------------------------------------------------------

    def confirm_match(self, match_id: int, discord_uid: int) -> tuple[bool, bool]:
        """Record that a player confirmed a match. Returns (success, both_confirmed)."""
        return self._transition_manager.confirm_match(match_id, discord_uid)

    def is_match_confirmed(self, match_id: int) -> bool:
        """Check whether both players have confirmed a match."""
        return self._transition_manager.is_match_confirmed(match_id)

    def abort_match(self, match_id: int, discord_uid: int) -> tuple[bool, str | None]:
        """Abort a match on behalf of a player."""
        return self._transition_manager.abort_match(match_id, discord_uid)

    def handle_confirmation_timeout(self, match_id: int) -> tuple[bool, str | None]:
        """Handle expiry of the confirmation window."""
        return self._transition_manager.handle_confirmation_timeout(match_id)

    def report_match_result(
        self,
        match_id: int,
        discord_uid: int,
        report: str,
    ) -> tuple[bool, str | None, Matches1v1Row | None]:
        """Record one player's result report. Returns (success, message, finalised_match)."""
        return self._transition_manager.report_match_result(
            match_id, discord_uid, report
        )

    # ------------------------------------------------------------------
    # Replay auto-resolution
    # ------------------------------------------------------------------

    def replay_auto_resolve_match(
        self,
        match_id: int,
        uploader_discord_uid: int,
        replay_result: str,
    ) -> Matches1v1Row:
        """Auto-resolve a match from a validated replay.

        ``replay_result`` must already be in match-player terms.
        """
        return self._transition_manager.replay_auto_resolve_match(
            match_id, uploader_discord_uid, replay_result
        )

    # ------------------------------------------------------------------
    # Replay 1v1
    # ------------------------------------------------------------------

    def insert_replay_1v1_pending(
        self,
        match_id: int,
        discord_uid: int,
        parsed: dict,
        initial_path: str,
        uploaded_at: datetime,
    ) -> dict:
        """Insert a replay row with upload_status='pending'. Returns the created row."""
        return self._transition_manager.insert_replay_1v1_pending(
            match_id, discord_uid, parsed, initial_path, uploaded_at
        )

    def update_replay_status(
        self,
        replay_id: int,
        status: str,
        final_path: str | None = None,
    ) -> None:
        """Update upload_status (and optionally replay_path) for a replay row."""
        self._transition_manager.update_replay_status(replay_id, status, final_path)

    def update_match_replay_refs(
        self,
        match_id: int,
        player_num: int,
        replay_path: str,
        replay_row_id: int,
        uploaded_at: datetime,
    ) -> None:
        """Update match row with latest replay path, row ID, and upload timestamp."""
        self._transition_manager.update_match_replay_refs(
            match_id, player_num, replay_path, replay_row_id, uploaded_at
        )

    # ------------------------------------------------------------------
    # Replay 2v2
    # ------------------------------------------------------------------

    def replay_auto_resolve_match_2v2(
        self,
        match_id: int,
        uploader_discord_uid: int,
        replay_result: str,
    ) -> Matches2v2Row:
        """Auto-resolve a 2v2 match from a validated replay."""
        return self._transition_manager.replay_auto_resolve_match_2v2(
            match_id, uploader_discord_uid, replay_result
        )

    def insert_replay_2v2_pending(
        self,
        match_id: int,
        discord_uid: int,
        parsed: dict,
        initial_path: str,
        uploaded_at: datetime,
    ) -> dict:
        """Insert a 2v2 replay row with upload_status='pending'."""
        return self._transition_manager.insert_replay_2v2_pending(
            match_id, discord_uid, parsed, initial_path, uploaded_at
        )

    def update_replay_2v2_status(
        self,
        replay_id: int,
        status: str,
        final_path: str | None = None,
    ) -> None:
        """Update upload_status for a 2v2 replay row."""
        self._transition_manager.update_replay_2v2_status(replay_id, status, final_path)

    def update_match_2v2_replay_refs(
        self,
        match_id: int,
        team_num: int,
        replay_path: str,
        replay_row_id: int,
        uploaded_at: datetime,
    ) -> None:
        """Update 2v2 match row with latest replay path, row ID, and upload timestamp."""
        self._transition_manager.update_match_2v2_replay_refs(
            match_id, team_num, replay_path, replay_row_id, uploaded_at
        )

    # ------------------------------------------------------------------
    # Admin operations
    # ------------------------------------------------------------------

    def reset_player_status(
        self, discord_uid: int
    ) -> tuple[bool, str | None, str | None]:
        """Reset player to idle. Returns (success, error, old_status)."""
        return self._transition_manager.reset_player_status(discord_uid)

    def toggle_ban(self, discord_uid: int) -> tuple[bool, bool]:
        """Toggle ban status. Returns (success, new_is_banned)."""
        return self._transition_manager.toggle_ban(discord_uid)

    def admin_resolve_match(
        self, match_id: int, result: str, admin_discord_uid: int
    ) -> dict:
        """Admin-resolve a match bypassing the two-report flow."""
        return self._transition_manager.admin_resolve_match(
            match_id, result, admin_discord_uid
        )

    def admin_resolve_match_2v2(
        self, match_id: int, result: str, admin_discord_uid: int
    ) -> dict:
        """Admin-resolve a 2v2 match bypassing the two-report flow."""
        return self._transition_manager.admin_resolve_match_2v2(
            match_id, result, admin_discord_uid
        )

    def admin_set_mmr(
        self, discord_uid: int, race: str, new_mmr: int
    ) -> tuple[bool, int | None]:
        """Idempotent SET of a player's MMR. Returns (success, old_mmr)."""
        return self._transition_manager.admin_set_mmr(discord_uid, race, new_mmr)

    # ------------------------------------------------------------------
    # Owner operations
    # ------------------------------------------------------------------

    def toggle_admin_role(self, discord_uid: int, discord_username: str) -> dict:
        """Toggle a user between admin and inactive roles."""
        return self._transition_manager.toggle_admin_role(discord_uid, discord_username)

    def get_announcement_recipient_uids(
        self, *, debug: bool, owners_only: bool, require_setup: bool
    ) -> list[int]:
        """Return the Discord UIDs that should receive an /owner announcement."""
        return self._state_reader.get_announcement_recipient_uids(
            debug=debug, owners_only=owners_only, require_setup=require_setup
        )

    # ------------------------------------------------------------------
    # Admin snapshot
    # ------------------------------------------------------------------

    def get_queue_snapshot_1v1(self) -> list[QueueEntry1v1]:
        """Return the current 1v1 queue."""
        return self._transition_manager.get_queue_snapshot_1v1()

    def get_active_matches_1v1(self) -> list[Matches1v1Row]:
        """Return all matches with match_result IS NULL."""
        return self._transition_manager.get_active_matches_1v1()

    def get_queue_snapshot_2v2(self) -> list[QueueEntry2v2]:
        """Return the current 2v2 queue."""
        return self._transition_manager.get_queue_snapshot_2v2()

    def get_active_matches_2v2(self) -> list[Matches2v2Row]:
        """Return all 2v2 matches with match_result IS NULL."""
        return self._transition_manager.get_active_matches_2v2()

    def get_parties_snapshot(self) -> list[dict]:
        """Return all active parties enriched with nationality."""
        return self._state_reader.get_parties_snapshot()

    # ------------------------------------------------------------------
    # Leaderboard
    # ------------------------------------------------------------------

    def get_leaderboard_1v1(self) -> list[LeaderboardEntry1v1]:
        """Return the current 1v1 leaderboard."""
        return list(self._state_reader.get_leaderboard_1v1())

    def get_leaderboard_2v2(self) -> list[LeaderboardEntry2v2]:
        """Return the current 2v2 leaderboard."""
        return list(self._state_reader.get_leaderboard_2v2())

    def enrich_match_with_ranks(self, match_dict: dict) -> dict:
        """Return a copy of match_dict with player letter ranks from the leaderboard."""
        return self._state_reader.enrich_match_with_ranks(match_dict)

    def enrich_match_2v2_with_ranks(self, match_dict: dict) -> dict:
        """Return a copy of match_dict with team letter ranks from the 2v2 leaderboard."""
        return self._state_reader.enrich_match_2v2_with_ranks(match_dict)

    def consume_leaderboard_dirty(self) -> bool:
        """Return True if the leaderboard was rebuilt since the last check."""
        return self._transition_manager.consume_leaderboard_dirty()

    # ------------------------------------------------------------------
    # Event logging
    # ------------------------------------------------------------------

    def log_event(self, row: dict) -> None:
        """Insert a single event row. Non-critical — failures are swallowed."""
        self._transition_manager.log_event(row)

    # ------------------------------------------------------------------
    # Survey writes
    # ------------------------------------------------------------------

    def save_setup_survey(
        self, discord_uid: int, q1: str, q2: str, q3: str, q4: list[str]
    ) -> None:
        """Persist setup survey responses. Write-only — no in-memory state."""
        self._transition_manager.save_setup_survey(discord_uid, q1, q2, q3, q4)

    def log_referral_pitch(self, discord_uid: int) -> None:
        """Log that a player generated their referral pitch embed."""
        self._transition_manager.log_referral_pitch(discord_uid)

    # ------------------------------------------------------------------
    # Queue join analytics (/activity)
    # ------------------------------------------------------------------

    def fetch_deduped_queue_joins(
        self,
        start: datetime,
        end: datetime,
        game_mode: str,
    ) -> list[datetime]:
        """Fetch queue_join events in range and apply the per-uid dedupe window.

        Centralized so ``/activity`` charts and the activity-status embed agree
        on the same "one join per player per slot" counting rule.
        """

        reader = DatabaseReader()
        events = reader.fetch_queue_join_events(start, end, game_mode)
        return dedupe_per_fixed_window(
            events, ACTIVITY_QUEUE_JOIN_DEDUPE_WINDOW_MINUTES
        )

    def get_queue_join_analytics(
        self,
        start: datetime,
        end: datetime,
        game_mode: str,
        *,
        bucket_minutes: int | None = None,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Return ``(bucket_minutes, [{ "t": iso, "count": int }, ...])``."""

        bucket = bucket_minutes or ACTIVITY_QUEUE_JOIN_CHART_BUCKET_MINUTES
        kept_times = self.fetch_deduped_queue_joins(start, end, game_mode)
        buckets = bucket_queue_join_counts(kept_times, start, end, bucket)
        rows: list[dict[str, Any]] = [
            {"t": bt.isoformat(), "count": c} for bt, c in buckets
        ]
        return bucket, rows

    # ------------------------------------------------------------------
    # Notifications (/notifyme)
    # ------------------------------------------------------------------

    def get_notifications(self, discord_uid: int) -> NotificationsRow | None:
        """Cached notifications row only — use ensure for create."""

        return self._state_reader.get_notifications_row(discord_uid)

    def ensure_notifications(self, discord_uid: int) -> dict:
        """Create default notifications row when missing and return it as dict."""

        return self._transition_manager.ensure_notification_row(discord_uid)

    def upsert_notifications(
        self,
        discord_uid: int,
        *,
        notify_queue_1v1: bool | None = None,
        notify_queue_2v2: bool | None = None,
        notify_queue_ffa: bool | None = None,
        notify_queue_1v1_cooldown: int | None = None,
        notify_queue_2v2_cooldown: int | None = None,
        notify_queue_ffa_cooldown: int | None = None,
    ) -> dict:
        """Persist notification preference updates."""

        return self._transition_manager.upsert_notifications_preferences(
            discord_uid,
            notify_queue_1v1=notify_queue_1v1,
            notify_queue_2v2=notify_queue_2v2,
            notify_queue_ffa=notify_queue_ffa,
            notify_queue_1v1_cooldown=notify_queue_1v1_cooldown,
            notify_queue_2v2_cooldown=notify_queue_2v2_cooldown,
            notify_queue_ffa_cooldown=notify_queue_ffa_cooldown,
        )

    def build_queue_join_activity_payload(
        self,
        joiner_uid: int,
        game_mode: str,
    ) -> dict[str, Any]:
        """Subscribers + footers for ``queue_join_activity`` WS event.

        Updates notifications DataFrame last_sent timestamps and logs the wave
        to the events table via record_notify_wave.
        """

        now = utc_now()
        uids, footers, locales, cooldowns = compute_queue_activity_targets(
            joiner_uid,
            game_mode,
            now,
        )
        if uids:
            self._transition_manager.record_notify_wave(uids, game_mode, now, cooldowns)

        # Derive queue_type: "bw", "sc2", or "both" from the joiner's queue entry.
        queue_type: str | None = None
        if game_mode == "1v1":
            entry = self._state_reader.get_queue_entry_1v1(joiner_uid)
            if entry:
                has_bw = entry.get("bw_race") is not None
                has_sc2 = entry.get("sc2_race") is not None
                if has_bw and has_sc2:
                    queue_type = "both"
                elif has_bw:
                    queue_type = "bw"
                elif has_sc2:
                    queue_type = "sc2"
        elif game_mode == "2v2":
            entry_2v2 = self._state_reader.get_queue_entry_2v2(joiner_uid)
            if entry_2v2:
                has_bw = (
                    entry_2v2.get("pure_bw_leader_race") is not None
                    and entry_2v2.get("pure_bw_member_race") is not None
                )
                has_sc2 = (
                    entry_2v2.get("pure_sc2_leader_race") is not None
                    and entry_2v2.get("pure_sc2_member_race") is not None
                )
                has_mixed = (
                    entry_2v2.get("mixed_leader_race") is not None
                    and entry_2v2.get("mixed_member_race") is not None
                )
                if has_mixed or (has_bw and has_sc2):
                    queue_type = "both"
                elif has_bw:
                    queue_type = "bw"
                elif has_sc2:
                    queue_type = "sc2"

        return {
            "game_mode": game_mode,
            "joiner_discord_uid": joiner_uid,
            "notify_discord_uids": uids,
            "footers": footers,
            "locales": locales,
            "queue_type": queue_type,
        }
