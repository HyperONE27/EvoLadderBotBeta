from backend.orchestrator.state import StateManager

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None


class TransitionManager:
    def __init__(self) -> None:
        if _state_manager is None:
            raise RuntimeError(_MODULE_NOT_INITIALIZED)

    def transition(self, state_manager: StateManager) -> None:
        pass
