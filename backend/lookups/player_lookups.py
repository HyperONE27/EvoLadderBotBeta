import polars as pl

from backend.domain_types.dataframes import PlayersRow
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

    return PlayersRow(**rows[0])  # type: ignore[no-any-return, typeddict-item]


def get_player_by_discord_username(discord_username: str) -> PlayersRow | None:
    """Get a player by their Discord username."""
    df = _get_players()
    if df.is_empty():
        return None

    rows = df.filter(pl.col("discord_username") == discord_username).to_dicts()
    if not rows:
        return None

    return PlayersRow(**rows[0])  # type: ignore[no-any-return, typeddict-item]


def get_player_by_player_name(player_name: str) -> PlayersRow | None:
    """Get a player by their player name."""
    df = _get_players()
    if df.is_empty():
        return None

    rows = df.filter(pl.col("player_name") == player_name).to_dicts()
    if not rows:
        return None

    return PlayersRow(**rows[0])  # type: ignore[no-any-return, typeddict-item]


def get_player_by_battletag(battletag: str) -> PlayersRow | None:
    """Get a player by their battletag."""
    df = _get_players()
    if df.is_empty():
        return None

    rows = df.filter(pl.col("battletag") == battletag).to_dicts()
    if not rows:
        return None

    return PlayersRow(**rows[0])  # type: ignore[no-any-return, typeddict-item]


# ----------------
# Module lifecycle
# ----------------


def init_player_lookups(state_manager: StateManager) -> None:
    """Initialize the player lookups module."""
    global _state_manager
    _state_manager = state_manager
