import polars as pl

from backend.domain_types.dataframes import AdminsRow, row_as
from backend.orchestrator.state import StateManager

_state_manager: StateManager | None = None


def init_admin_lookups(state_manager: StateManager) -> None:
    global _state_manager
    _state_manager = state_manager


def get_admin_by_discord_uid(discord_uid: int) -> AdminsRow | None:
    """Return the admin row for the given Discord UID, or None."""
    if _state_manager is None:
        raise RuntimeError(f"{__name__} not initialized")
    df = _state_manager.admins_df
    rows = df.filter(pl.col("discord_uid") == discord_uid)
    if rows.is_empty():
        return None
    return row_as(AdminsRow, rows.row(0, named=True))
