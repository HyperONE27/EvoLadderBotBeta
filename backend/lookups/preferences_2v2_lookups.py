import polars as pl

from backend.domain_types.dataframes import Preferences2v2Row, row_as
from backend.orchestrator.state import StateManager

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None


def _get_state_manager() -> StateManager:
    if _state_manager is None:
        raise RuntimeError(_MODULE_NOT_INITIALIZED)
    return _state_manager


def _get_preferences_2v2() -> pl.DataFrame:
    return _get_state_manager().preferences_2v2_df


def get_preferences_2v2_by_discord_uid(discord_uid: int) -> Preferences2v2Row | None:
    """Get a player's 2v2 queue preferences by their Discord UID."""
    df = _get_preferences_2v2()
    if df.is_empty():
        return None

    rows = df.filter(pl.col("discord_uid") == discord_uid).to_dicts()
    if not rows:
        return None

    return row_as(Preferences2v2Row, rows[0])


def init_preferences_2v2_lookups(state_manager: StateManager) -> None:
    """Initialize the preferences 2v2 lookups module."""
    global _state_manager
    _state_manager = state_manager
