from backend.database.database import DatabaseWriter
from backend.domain_types.dataframes import Matches1v1Row, MMRs1v1Row, PlayersRow
from backend.orchestrator.reader import StateReader
from backend.orchestrator.state import StateManager
from backend.orchestrator.transitions import TransitionManager


class Orchestrator:
    def __init__(self, state_manager: StateManager, db_writer: DatabaseWriter) -> None:
        self._state_reader = StateReader(state_manager)
        self._transition_manager = TransitionManager(state_manager, db_writer)

    def get_match_1v1(self, match_id: int) -> Matches1v1Row | None:
        """Get a 1v1 match by its ID."""
        return self._state_reader.get_match_1v1(match_id)

    def get_mmr_1v1(self, discord_uid: int, race: str) -> MMRs1v1Row | None:
        """Get a 1v1 MMR for a player by their Discord UID and race."""
        return self._state_reader.get_mmr_1v1(discord_uid, race)

    def get_player(self, discord_uid: int) -> PlayersRow | None:
        """Get a player by their Discord UID."""
        return self._state_reader.get_player(discord_uid)

    def setcountry(
        self, discord_uid: int, discord_username: str, country_name: str
    ) -> tuple[bool, str | None]:
        """Set the country for a player."""
        # This is a write operation, go straight to the transition manager
        return self._transition_manager.set_country_for_player(
            discord_uid, discord_username, country_name
        )

    def setup(
        self,
        discord_uid: int,
        discord_username: str,
        player_name: str,
        alt_player_names: list[str] | None,
        battletag: str,
        country_name: str,
        region_name: str,
        language: str,
    ) -> tuple[bool, str | None]:
        """Setup a new player."""
        return self._transition_manager.setup_player(
            discord_uid,
            discord_username,
            player_name,
            alt_player_names,
            battletag,
            country_name,
            region_name,
            language,
        )
