from typing import Dict
from server.backend.orchestrator.state_manager import StateManager
from server.backend.types.json_types import Mod

ERROR_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

def init_mod_utils(state_manager: StateManager) -> None:
    global _state_manager
    _state_manager = state_manager