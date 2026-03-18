import polars as pl

from backend.domain_types.dataframes import Matches1v1Row, row_as
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


def _get_matches_1v1() -> pl.DataFrame:
    return _get_state_manager().matches_1v1_df


# ----------------
# Public interface
# ----------------


def get_match_1v1_by_id(id: int) -> Matches1v1Row | None:
    """Get a match by its ID."""
    df = _get_matches_1v1()
    if df.is_empty():
        return None

    rows = df.filter(pl.col("id") == id).to_dicts()
    if not rows:
        return None

    return row_as(Matches1v1Row, rows[0])


def get_matches_1v1_by_discord_uid(discord_uid: int) -> list[Matches1v1Row] | None:
    """Get all matches by a Discord UID."""
    df = _get_matches_1v1()
    if df.is_empty():
        return []

    rows = df.filter(
        (pl.col("player_1_discord_uid") == discord_uid)
        | (pl.col("player_2_discord_uid") == discord_uid)
    ).to_dicts()
    if not rows:
        return None

    return [row_as(Matches1v1Row, row) for row in rows]


def get_matches_1v1_by_race(race: str) -> list[Matches1v1Row] | None:
    """Get all matches by a race."""
    df = _get_matches_1v1()
    if df.is_empty():
        return []

    rows = df.filter(
        (pl.col("player_1_race") == race) | (pl.col("player_2_race") == race)
    ).to_dicts()
    if not rows:
        return None

    return [row_as(Matches1v1Row, row) for row in rows]


def get_matches_1v1_by_map_name(map_name: str) -> list[Matches1v1Row] | None:
    """Get all matches by a map name."""
    df = _get_matches_1v1()
    if df.is_empty():
        return []

    rows = df.filter(pl.col("map_name") == map_name).to_dicts()
    if not rows:
        return None

    return [row_as(Matches1v1Row, row) for row in rows]


def get_matches_1v1_by_server_name(server_name: str) -> list[Matches1v1Row] | None:
    """Get all matches by a server name."""
    df = _get_matches_1v1()
    if df.is_empty():
        return []

    rows = df.filter(pl.col("server_name") == server_name).to_dicts()
    if not rows:
        return None

    return [row_as(Matches1v1Row, row) for row in rows]


def get_matches_1v1_by_two_discord_uids(
    discord_uid_1: int, discord_uid_2: int
) -> list[Matches1v1Row] | None:
    """Get all matches by two Discord UIDs."""
    df = _get_matches_1v1()
    if df.is_empty():
        return []

    rows = df.filter(
        (pl.col("player_1_discord_uid") == discord_uid_1)
        & (pl.col("player_2_discord_uid") == discord_uid_2)
    ).to_dicts()
    if not rows:
        return None

    return [row_as(Matches1v1Row, row) for row in rows]


# ----------------
# Module lifecycle
# ----------------


def init_match_1v1_lookups(state_manager: StateManager) -> None:
    """Initialize the match 1v1 lookups module."""
    global _state_manager
    _state_manager = state_manager
