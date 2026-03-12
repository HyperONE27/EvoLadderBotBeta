import polars as pl

from backend.domain_types.dataframes import MMRs1v1Row
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


def _get_mmrs_1v1() -> pl.DataFrame:
    return _get_state_manager().mmrs_1v1_df


# ----------------
# Public interface
# ----------------


def get_mmrs_1v1_by_discord_uid(discord_uid: int) -> list[MMRs1v1Row] | None:
    """Get all MMRS by a Discord UID."""
    df = _get_mmrs_1v1()
    if df.is_empty():
        return []

    rows = df.filter(pl.col("discord_uid") == discord_uid).to_dicts()
    if not rows:
        return None

    return [MMRs1v1Row(**row) for row in rows]  # type: ignore[typeddict-item]


def get_mmrs_1v1_by_race(race: str) -> list[MMRs1v1Row] | None:
    """Get all MMRS by a race."""
    df = _get_mmrs_1v1()
    if df.is_empty():
        return []

    rows = df.filter(pl.col("race") == race).to_dicts()
    if not rows:
        return None

    return [MMRs1v1Row(**row) for row in rows]  # type: ignore[typeddict-item]


def get_mmr_1v1_by_discord_uid_and_race(
    discord_uid: int, race: str
) -> MMRs1v1Row | None:
    """Get a MMR by a Discord UID and race."""
    df = _get_mmrs_1v1()
    if df.is_empty():
        return None

    rows = df.filter(
        pl.col("discord_uid") == discord_uid, pl.col("race") == race
    ).to_dicts()
    if not rows:
        return None

    return MMRs1v1Row(**rows[0])  # type: ignore[no-any-return, typeddict-item]


# ----------------
# Module lifecycle
# ----------------


def init_mmr_1v1_lookups(state_manager: StateManager) -> None:
    """Initialize the MMRS 1v1 lookups module."""
    global _state_manager
    _state_manager = state_manager
