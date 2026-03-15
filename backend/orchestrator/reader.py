from backend.domain_types.dataframes import (
    Matches1v1Row,
    MMRs1v1Row,
    PlayersRow,
)
from backend.lookups.match_1v1_lookups import get_match_1v1_by_id
from backend.lookups.mmr_1v1_lookups import (
    get_mmr_1v1_by_discord_uid_and_race,
    get_mmrs_1v1_by_discord_uid,
)
from backend.lookups.player_lookups import get_player_by_discord_uid
from backend.orchestrator.state import StateManager


class StateReader:
    def __init__(self, state_manager: StateManager) -> None:
        self._state_manager = state_manager

    def get_all_mmrs_1v1(self, discord_uid: int) -> list[MMRs1v1Row]:
        """Get all 1v1 MMR rows for a player."""
        return get_mmrs_1v1_by_discord_uid(discord_uid) or []

    def get_match_1v1(self, match_id: int) -> Matches1v1Row | None:
        """Get a 1v1 match by its ID."""
        return get_match_1v1_by_id(match_id)

    def get_mmr_1v1(self, discord_uid: int, race: str) -> MMRs1v1Row | None:
        """Get a 1v1 MMR for a player by their Discord UID and race."""
        return get_mmr_1v1_by_discord_uid_and_race(discord_uid, race)

    def get_player(self, discord_uid: int) -> PlayersRow | None:
        """Get a player by their Discord UID."""
        return get_player_by_discord_uid(discord_uid)


