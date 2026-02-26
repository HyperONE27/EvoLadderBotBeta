from typing import Dict
from server.backend.orchestrator.state_manager import StateManager
from server.backend.types.json_types import Emote

ERROR_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------

def _get_emote_by_name(name: str) -> Emote | None:
    if _state_manager is None:
        raise RuntimeError(ERROR_MODULE_NOT_INITIALIZED)
    return _state_manager.emotes.get(name)

def _get_emote_by_short_name(short_name: str) -> Emote | None:
    if _state_manager is None:
        raise RuntimeError(ERROR_MODULE_NOT_INITIALIZED)
    return next((emote for emote in _state_manager.emotes.values() if emote["short_name"] == short_name), None)

def _get_emote_by_markdown(markdown: str) -> Emote | None:
    if _state_manager is None:
        raise RuntimeError(ERROR_MODULE_NOT_INITIALIZED)
    return next((emote for emote in _state_manager.emotes.values() if emote["markdown"] == markdown), None)

# ----------
# Public API
# ----------

def init_emote_utils(state_manager: StateManager) -> None:
    global _state_manager
    _state_manager = state_manager

def get_emote_name_by_short_name(short_name: str) -> str | None:
    if _state_manager is None:
        raise RuntimeError(ERROR_MODULE_NOT_INITIALIZED)
    emote = _get_emote_by_short_name(short_name)
    return emote["name"] if emote else None

def get_emote_name_by_markdown(markdown: str) -> str | None:
    if _state_manager is None:
        raise RuntimeError(ERROR_MODULE_NOT_INITIALIZED)
    emote = _get_emote_by_markdown(markdown)
    return emote["name"] if emote else None