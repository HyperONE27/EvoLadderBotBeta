from datetime import datetime
from server.backend.orchestrator.state import StateManager
from server.backend.types.polars_dataframes import PlayersRow

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------

def _get_state_manager() -> StateManager:
    if _state_manager is None:
        raise RuntimeError(_MODULE_NOT_INITIALIZED)
    return _state_manager


def _get_players() -> dict[int, PlayersRow]:
    """Convert players dataframe to denormalized dict keyed by player ID."""
    df = _get_state_manager().players_df

    # Convert to list of dicts (automatically converts Polars types to Python types)
    players_dicts = df.to_dicts()

    # Convert to dict keyed by player ID with proper typing
    players: dict[int, PlayersRow] = {}

    for player_dict in players_dicts:
        player_id = player_dict["id"]

        # Handle datetime conversions from Polars to Python datetime
        if player_dict.get("accepted_tos_at") is not None:
            player_dict["accepted_tos_at"] = player_dict["accepted_tos_at"].to_pydatetime()
        if player_dict.get("completed_setup_at") is not None:
            player_dict["completed_setup_at"] = player_dict["completed_setup_at"].to_pydatetime()

        # Create PlayersRow object and store in dict
        players[player_id] = PlayersRow(**player_dict)

    return players


# ----------------
# Public interface
# ----------------

def get_player_by_id(player_id: int) -> PlayersRow | None:
    """Get a player by their ID."""
    players = _get_players()
    return players.get(player_id)


def get_player_by_discord_uid(discord_uid: int) -> PlayersRow | None:
    """Get a player by their Discord UID."""
    players = _get_players()

    for player in players.values():
        if player["discord_uid"] == discord_uid:
            return player

    return None


def get_all_players() -> list[PlayersRow]:
    """Get all players as a list."""
    players = _get_players()
    return list(players.values())


def is_player_banned(player_id: int) -> bool:
    """Check if a player is banned."""
    player = get_player_by_id(player_id)
    return player["is_banned"] if player else False


def get_active_players() -> list[PlayersRow]:
    """Get all non-banned players."""
    players = _get_players()
    return [p for p in players.values() if not p["is_banned"]]


# ----------------
# Module lifecycle
# ----------------

def initialize(state_manager: StateManager) -> None:
    """Initialize the player lookups module."""
    global _state_manager
    _state_manager = state_manager