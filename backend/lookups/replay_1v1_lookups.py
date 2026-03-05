import polars as pl

from backend.orchestrator.state import StateManager
from backend.domain_types.polars_dataframes import Replays1v1Row

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

    return Replays1v1Row(**rows[0])  # type: ignore[no-any-return, typeddict-item]


def get_replay_1v1_by_replay_path(replay_path: str) -> Replays1v1Row | None:
    """Get a replay by its replay path."""
    df = _get_replays_1v1()
    if df.is_empty():
        return None

    rows = df.filter(pl.col("replay_path") == replay_path).to_dicts()
    if not rows:
        return None

    return Replays1v1Row(**rows[0])  # type: ignore[no-any-return, typeddict-item]


def get_replay_1v1_by_replay_hash(replay_hash: str) -> Replays1v1Row | None:
    """Get a replay by its replay hash."""
    df = _get_replays_1v1()
    if df.is_empty():
        return None

    rows = df.filter(pl.col("replay_hash") == replay_hash).to_dicts()
    if not rows:
        return None

    return Replays1v1Row(**rows[0])  # type: ignore[no-any-return, typeddict-item]


# ----------------
# Module lifecycle
# ----------------


def init_replay_1v1_lookups(state_manager: StateManager) -> None:
    """Initialize the replay 1v1 lookups module."""
    global _state_manager
    _state_manager = state_manager
