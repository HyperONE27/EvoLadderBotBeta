import polars as pl

from backend.domain_types.dataframes import ContentCreatorsRow, row_as
from backend.orchestrator.state import StateManager

_state_manager: StateManager | None = None


def init_content_creator_lookups(state_manager: StateManager) -> None:
    global _state_manager
    _state_manager = state_manager


def get_content_creator_by_discord_uid(
    discord_uid: int,
) -> ContentCreatorsRow | None:
    """Return the content_creator row for the given Discord UID, or None."""
    if _state_manager is None:
        raise RuntimeError(f"{__name__} not initialized")
    df = _state_manager.content_creators_df
    rows = df.filter(pl.col("discord_uid") == discord_uid)
    if rows.is_empty():
        return None
    return row_as(ContentCreatorsRow, rows.row(0, named=True))


def is_content_creator(discord_uid: int) -> bool:
    """True if the Discord UID is listed in the content_creators table."""
    return get_content_creator_by_discord_uid(discord_uid) is not None
