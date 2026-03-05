import polars as pl

from server.backend.orchestrator.state import StateManager
from server.backend.types.polars_dataframes import Preferences1v1Row

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------


def _get_state_manager() -> StateManager:
    if _state_manager is None:
        raise RuntimeError(_MODULE_NOT_INITIALIZED)
    return _state_manager


def _get_preferences_1v1() -> pl.DataFrame:
    return _get_state_manager().preferences_1v1_df


# ----------------
# Public interface
# ----------------


def get_preferences_1v1_by_discord_uid(discord_uid: int) -> Preferences1v1Row | None:
    """Get a player's preferences by their Discord UID."""
    df = _get_preferences_1v1()
    if df.is_empty():
        return None

    rows = df.filter(pl.col("discord_uid") == discord_uid).to_dicts()
    if not rows:
        return None

    return Preferences1v1Row(**rows[0])  # type: ignore[no-any-return, typeddict-item]


# ----------------
# Module lifecycle
# ----------------


def init_preferences_1v1_lookups(state_manager: StateManager) -> None:
    """Initialize the preferences 1v1 lookups module."""
    global _state_manager
    _state_manager = state_manager
