from backend.database.database import DatabaseWriter
from backend.domain_types.dataframes import (
    Matches1v1Row,
    MMRs1v1Row,
    PlayersRow,
    Preferences1v1Row,
)
from backend.domain_types.ephemeral import QueueEntry1v1
from backend.orchestrator.reader import StateReader
from backend.orchestrator.state import StateManager
from backend.orchestrator.transitions import TransitionManager


class Orchestrator:
    def __init__(self, state_manager: StateManager, db_writer: DatabaseWriter) -> None:
        self._state_reader = StateReader(state_manager)
        self._transition_manager = TransitionManager(state_manager, db_writer)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_match_1v1(self, match_id: int) -> Matches1v1Row | None:
        """Get a 1v1 match by its ID."""
        return self._state_reader.get_match_1v1(match_id)

    def get_mmr_1v1(self, discord_uid: int, race: str) -> MMRs1v1Row | None:
        """Get a 1v1 MMR for a player by their Discord UID and race."""
        return self._state_reader.get_mmr_1v1(discord_uid, race)

    def get_player(self, discord_uid: int) -> PlayersRow | None:
        """Get a player by their Discord UID."""
        return self._state_reader.get_player(discord_uid)

    def get_preferences_1v1(self, discord_uid: int) -> Preferences1v1Row | None:
        """Get a player's 1v1 preferences by their Discord UID."""
        return self._state_reader.get_preferences_1v1(discord_uid)

    def get_profile(
        self, discord_uid: int
    ) -> tuple[PlayersRow | None, list[MMRs1v1Row]]:
        """Get a player's profile: their player row and all 1v1 MMR rows."""
        player = self._state_reader.get_player(discord_uid)
        mmrs = self._state_reader.get_all_mmrs_1v1(discord_uid)
        return player, mmrs

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
        }

    # ------------------------------------------------------------------
    # Player management
    # ------------------------------------------------------------------

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
    # Matchmaking
    # ------------------------------------------------------------------

    def run_matchmaking_wave(self) -> list[Matches1v1Row]:
        """Run one matchmaking wave using the current queue snapshot."""
        queue_snapshot = self._state_reader.get_queue_1v1()
        return self._transition_manager.run_matchmaking_wave(queue_snapshot)

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
