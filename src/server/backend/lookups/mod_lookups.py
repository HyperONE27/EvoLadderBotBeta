from server.backend.orchestrator.state import StateManager
from server.backend.types.json_types import Mod

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------


def _check_initialized() -> None:
    if _state_manager is None:
        raise RuntimeError(_MODULE_NOT_INITIALIZED)


def _get_mods() -> dict[str, Mod]:
    _check_initialized()
    return _state_manager.mods


# ----------
# Public API
# ----------


def init_mod_lookups(state_manager: StateManager) -> None:
    global _state_manager
    _state_manager = state_manager


def get_mod_by_code(code: str) -> Mod | None:
    _check_initialized()
    return _get_mods().get(code)


def get_mod_by_name(name: str) -> Mod | None:
    _check_initialized()
    return next((mod for mod in _get_mods().values() if mod["name"] == name), None)


def get_mod_by_short_name(short_name: str) -> Mod | None:
    _check_initialized()
    return next(
        (mod for mod in _get_mods().values() if mod["short_name"] == short_name), None
    )


def get_mod_by_link(link: str) -> Mod | None:
    _check_initialized()
    return next(
        (
            mod
            for mod in _get_mods().values()
            if link == mod["am_link"]
            or link == mod["eu_link"]
            or link == mod["as_link"]
        ),
        None,
    )
