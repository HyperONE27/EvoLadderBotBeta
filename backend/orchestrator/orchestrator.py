from backend.orchestrator.reader import StateReader
from backend.orchestrator.state import StateManager
from backend.orchestrator.transitions import TransitionManager


class Orchestrator:
    def __init__(self, state_manager: StateManager) -> None:
        self._state_reader = StateReader(state_manager)
        self._transition_manager = TransitionManager(state_manager)

    def setcountry(
        self, discord_uid: int, discord_username: str, country_name: str
    ) -> tuple[bool, str | None]:
        """Set the country for a player."""
        # This is a write operation, go straight to the transition manager
        self._transition_manager.set_country_for_player(
            discord_uid, discord_username, country_name
        )
        return False, None
