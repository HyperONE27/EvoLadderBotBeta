from backend.domain_types.dataframes import (
    Matches1v1Row,
    MMRs1v1Row,
    PlayersRow,
    Preferences1v1Row,
)
from backend.domain_types.ephemeral import QueueEntry1v1
from backend.lookups.match_1v1_lookups import get_match_1v1_by_id
from backend.lookups.mmr_1v1_lookups import (
    get_mmr_1v1_by_discord_uid_and_race,
    get_mmrs_1v1_by_discord_uid,
)
from backend.lookups.player_lookups import get_player_by_discord_uid
from backend.lookups.preferences_1v1_lookups import get_preferences_1v1_by_discord_uid
from backend.orchestrator.state import StateManager


class StateReader:
    def __init__(self, state_manager: StateManager) -> None:
        self._state_manager = state_manager

    # ------------------------------------------------------------------
    # Players
    # ------------------------------------------------------------------

    def get_player(self, discord_uid: int) -> PlayersRow | None:
        """Get a player by their Discord UID."""
        return get_player_by_discord_uid(discord_uid)

    # ------------------------------------------------------------------
    # MMR
    # ------------------------------------------------------------------

    def get_all_mmrs_1v1(self, discord_uid: int) -> list[MMRs1v1Row]:
        """Get all 1v1 MMR rows for a player."""
        return get_mmrs_1v1_by_discord_uid(discord_uid) or []

    def get_mmr_1v1(self, discord_uid: int, race: str) -> MMRs1v1Row | None:
        """Get a 1v1 MMR for a player by their Discord UID and race."""
        return get_mmr_1v1_by_discord_uid_and_race(discord_uid, race)

    # ------------------------------------------------------------------
    # Matches
    # ------------------------------------------------------------------

    def get_match_1v1(self, match_id: int) -> Matches1v1Row | None:
        """Get a 1v1 match by its ID."""
        return get_match_1v1_by_id(match_id)

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

    def get_queue_1v1(self) -> list[QueueEntry1v1]:
        """Return the current 1v1 queue (shallow copy)."""
        return list(self._state_manager.queue_1v1)

    def get_queue_entry_1v1(self, discord_uid: int) -> QueueEntry1v1 | None:
        """Find a specific player's queue entry, or None."""
        for entry in self._state_manager.queue_1v1:
            if entry["discord_uid"] == discord_uid:
                return entry
        return None

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    def get_preferences_1v1(self, discord_uid: int) -> Preferences1v1Row | None:
        """Get a player's 1v1 queue preferences."""
        return get_preferences_1v1_by_discord_uid(discord_uid)

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------

    def get_player_location(self, discord_uid: int) -> str | None:
        """Return the geographic-region code for a player, or None."""
        player = get_player_by_discord_uid(discord_uid)
        if player is None:
            return None
        return player.get("location")
