from typing import Dict
from server.backend.orchestrator.state_manager import StateManager
from server.backend.types.json_types import CrossTableData

ERROR_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------

def _check_initialized() -> None:
    if _state_manager is None:
        raise RuntimeError(ERROR_MODULE_NOT_INITIALIZED)

# ----------
# Public API
# ----------

def init_cross_table_utils(state_manager: StateManager) -> None:
    global _state_manager
    _state_manager = state_manager