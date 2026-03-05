from server.backend.orchestrator.state import StateManager
from server.backend.types.json_types import Race

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------


def _get_state_manager() -> StateManager:
    if _state_manager is None:
        raise RuntimeError(_MODULE_NOT_INITIALIZED)
    return _state_manager


def _get_races() -> dict[str, Race]:
    return _get_state_manager().races


# ----------
# Public API
# ----------


def get_race_by_code(code: str) -> Race | None:
    return _get_races().get(code)


def get_race_by_name(name: str) -> Race | None:
    return next((race for race in _get_races().values() if race["name"] == name), None)


def get_race_by_short_name(short_name: str) -> Race | None:
    return next(
        (race for race in _get_races().values() if race["short_name"] == short_name),
        None,
    )


def get_race_by_alias(alias: str) -> Race | None:
    return next(
        (race for race in _get_races().values() if alias in race["aliases"]), None
    )


# ----------------
# Module lifecycle
# ----------------


def init_race_lookups(state_manager: StateManager) -> None:
    """Initialize the race lookups module."""
    global _state_manager
    _state_manager = state_manager
