from server.backend.orchestrator.state import StateManager
from server.backend.types.json_types import Emote

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------


def _check_initialized() -> None:
    if _state_manager is None:
        raise RuntimeError(_MODULE_NOT_INITIALIZED)


def _get_emotes() -> dict[str, Emote]:
    _check_initialized()
    return _state_manager.emotes


# ----------
# Public API
# ----------


def init_emote_lookups(state_manager: StateManager) -> None:
    global _state_manager
    _state_manager = state_manager


def get_emote_by_name(name: str) -> Emote | None:
    _check_initialized()
    return _get_emotes().get(name)


def get_emote_by_short_name(short_name: str) -> Emote | None:
    _check_initialized()
    return next(
        (
            emote
            for emote in _get_emotes().values()
            if emote["short_name"] == short_name
        ),
        None,
    )


def get_emote_by_markdown(markdown: str) -> Emote | None:
    _check_initialized()
    return next(
        (emote for emote in _get_emotes().values() if emote["markdown"] == markdown),
        None,
    )
