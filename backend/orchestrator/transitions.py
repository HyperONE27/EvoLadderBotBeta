from backend.orchestrator.state import StateManager


class TransitionManager:
    def __init__(self, state_manager: StateManager) -> None:
        self._state_manager = state_manager
