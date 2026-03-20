import polars as pl

from backend.domain_types.dataframes import PlayersRow, row_as
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


def _get_players() -> pl.DataFrame:
    return _get_state_manager().players_df


# ----------------
# Public interface
# ----------------


def get_player_by_discord_uid(discord_uid: int) -> PlayersRow | None:
    """Get a player by their Discord UID."""
    df = _get_players()
    if df.is_empty():
        return None

    rows = df.filter(pl.col("discord_uid") == discord_uid).to_dicts()
    if not rows:
        return None

    return row_as(PlayersRow, rows[0])


def get_player_by_discord_username(discord_username: str) -> PlayersRow | None:
    """Get a player by their Discord username."""
    df = _get_players()
    if df.is_empty():
        return None

    rows = df.filter(pl.col("discord_username") == discord_username).to_dicts()
    if not rows:
        return None

    return row_as(PlayersRow, rows[0])


def get_player_by_player_name(player_name: str) -> PlayersRow | None:
    """Get a player by their player name (case-insensitive match)."""
    df = _get_players()
    if df.is_empty():
        return None

    needle = player_name.lower()
    rows = df.filter(pl.col("player_name").str.to_lowercase() == needle).to_dicts()
    if not rows:
        return None

    return row_as(PlayersRow, rows[0])


def is_player_name_taken(
    player_name: str, exclude_discord_uid: int | None = None
) -> bool:
    """True if any row uses this player_name, compared case-insensitively."""
    df = _get_players()
    if df.is_empty():
        return False
    needle = player_name.lower()
    cond = pl.col("player_name").str.to_lowercase() == needle
    if exclude_discord_uid is not None:
        cond = cond & (pl.col("discord_uid") != exclude_discord_uid)
    return df.filter(cond).height > 0


def get_player_by_battletag(battletag: str) -> PlayersRow | None:
    """Get a player by their battletag."""
    df = _get_players()
    if df.is_empty():
        return None

    rows = df.filter(pl.col("battletag") == battletag).to_dicts()
    if not rows:
        return None

    return row_as(PlayersRow, rows[0])


# ----------------
# Module lifecycle
# ----------------


def init_player_lookups(state_manager: StateManager) -> None:
    """Initialize the player lookups module."""
    global _state_manager
    _state_manager = state_manager
