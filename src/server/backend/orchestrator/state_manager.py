"""Centralized state manager - owns all state in the backend."""

class StateManager:
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Basic data from data/ directory for looksups
        self._admins: 
        self._countries: 
        self._cross_table: 
        self._emotes: 
        self._leaderboard: 
        self._maps: 
        self._mods: 
        self._races: 
        self._regions: 

        # In-memory DataFrames (caching the entire database)
        self._players_df: Optional[pl.DataFrame] = None
        self._player_action_logs_df: Optional[pl.DataFrame] = None
        self._command_calls_df: Optional[pl.DataFrame] = None
        self._replays_df: Optional[pl.DataFrame] = None
        self._mmrs_1v1_df: Optional[pl.DataFrame] = None
        self._matches_1v1_df: Optional[pl.DataFrame] = None
        self._preferences_1v1_df: Optional[pl.DataFrame] = None
        self._admin_actions_df: Optional[pl.DataFrame] = None

        # System state