from backend.domain_types.dataframes import (
    AdminsRow,
    Matches1v1Row,
    MMRs1v1Row,
    PlayersRow,
    Preferences1v1Row,
)
from backend.domain_types.ephemeral import LeaderboardEntry1v1, QueueEntry1v1
from backend.lookups.admin_lookups import get_admin_by_discord_uid
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
    # Admins
    # ------------------------------------------------------------------

    def get_admin(self, discord_uid: int) -> AdminsRow | None:
        """Get an admin by their Discord UID."""
        return get_admin_by_discord_uid(discord_uid)

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
    # Leaderboard
    # ------------------------------------------------------------------

    def get_leaderboard_1v1(self) -> list[LeaderboardEntry1v1]:
        """Return the current 1v1 leaderboard."""
        return self._state_manager.leaderboard_1v1

    def enrich_match_with_ranks(self, match_dict: dict) -> dict:
        """Return a copy of match_dict with player letter ranks from the leaderboard."""
        enriched = dict(match_dict)
        leaderboard = self._state_manager.leaderboard_1v1
        lookup: dict[tuple[int, str], str] = {
            (e["discord_uid"], e["race"]): e["letter_rank"] for e in leaderboard
        }
        p1_uid: int | None = match_dict.get("player_1_discord_uid")
        p1_race: str | None = match_dict.get("player_1_race")
        p2_uid: int | None = match_dict.get("player_2_discord_uid")
        p2_race: str | None = match_dict.get("player_2_race")
        enriched["player_1_letter_rank"] = (
            lookup.get((p1_uid, p1_race), "U")
            if p1_uid is not None and p1_race
            else "U"
        )
        enriched["player_2_letter_rank"] = (
            lookup.get((p2_uid, p2_race), "U")
            if p2_uid is not None and p2_race
            else "U"
        )
        return enriched

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------

    def get_player_location(self, discord_uid: int) -> str | None:
        """Return the geographic-region code for a player, or None."""
        player = get_player_by_discord_uid(discord_uid)
        if player is None:
            return None
        return player.get("location")
