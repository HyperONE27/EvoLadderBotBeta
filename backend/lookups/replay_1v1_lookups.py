import polars as pl

from backend.domain_types.dataframes import Replays1v1Row, row_as
from backend.orchestrator.state import StateManager

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------


def _get_state_manager() -> StateManager:
    if _state_manager is None:
        raise RuntimeError(_MODULE_NOT_INITIALIZED)
    return _state_manager


def _get_replays_1v1() -> pl.DataFrame:
    return _get_state_manager().replays_1v1_df


# ----------------
# Public interface
# ----------------


def get_replay_1v1_by_id(id: int) -> Replays1v1Row | None:
    """Get a replay by its ID."""
    df = _get_replays_1v1()
    if df.is_empty():
        return None

    rows = df.filter(pl.col("id") == id).to_dicts()
    if not rows:
        return None

    return row_as(Replays1v1Row, rows[0])


def get_replay_1v1_by_replay_path(replay_path: str) -> Replays1v1Row | None:
    """Get a replay by its replay path."""
    df = _get_replays_1v1()
    if df.is_empty():
        return None

    rows = df.filter(pl.col("replay_path") == replay_path).to_dicts()
    if not rows:
        return None

    return row_as(Replays1v1Row, rows[0])


def get_replays_1v1_by_match_id(match_id: int) -> list[Replays1v1Row]:
    """Get all replays for a given match ID."""
    df = _get_replays_1v1()
    if df.is_empty():
        return []

    rows = df.filter(pl.col("matches_1v1_id") == match_id).to_dicts()
    return [row_as(Replays1v1Row, r) for r in rows]


def get_replay_1v1_by_replay_hash(replay_hash: str) -> Replays1v1Row | None:
    """Get a replay by its replay hash."""
    df = _get_replays_1v1()
    if df.is_empty():
        return None

    rows = df.filter(pl.col("replay_hash") == replay_hash).to_dicts()
    if not rows:
        return None

    return row_as(Replays1v1Row, rows[0])


# ----------------
# Module lifecycle
# ----------------


def init_replay_1v1_lookups(state_manager: StateManager) -> None:
    """Initialize the replay 1v1 lookups module."""
    global _state_manager
    _state_manager = state_manager
