from server.backend.orchestrator.state_manager import StateManager
from server.backend.types.json_types import Race

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------


def _check_initialized() -> None:
    if _state_manager is None:
        raise RuntimeError(_MODULE_NOT_INITIALIZED)


def _get_races() -> dict[str, Race]:
    _check_initialized()
    return _state_manager.races


# ----------
# Public API
# ----------


def init_race_utils(state_manager: StateManager) -> None:
    global _state_manager
    _state_manager = state_manager


def get_race_by_code(code: str) -> Race | None:
    _check_initialized()
    return _get_races().get(code)


def get_race_by_name(name: str) -> Race | None:
    _check_initialized()
    return next((race for race in _get_races().values() if race["name"] == name), None)


def get_race_by_short_name(short_name: str) -> Race | None:
    _check_initialized()
    return next(
        (race for race in _get_races().values() if race["short_name"] == short_name),
        None,
    )


def get_race_by_alias(alias: str) -> Race | None:
    _check_initialized()
    return next(
        (race for race in _get_races().values() if alias in race["aliases"]), None
    )
