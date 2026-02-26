from datetime import datetime, timezone
from typing import List, TypedDict

class QueueEntry1v1(TypedDict):
    discord_uid: int
    player_name: str
    bw_race: str | None  # Must be a key in state_manager.races and state_manager.races[bw_race]["is_bw_race"] must be True
    sc2_race: str | None # Must be a key in state_manager.races and state_manager.races[sc2_race]["is_sc2_race"] must be True
    bw_mmr: int | None
    sc2_mmr: int | None
    map_vetoes: List[str]   # Must be a key in state_manager.maps
    joined_at: datetime
    wait_cycles: int

class MatchCandidate1v1(TypedDict):
    player_1_discord_uid: int
    player_2_discord_uid: int
    player_1_name: str
    player_2_name: str
    player_1_race: str      # Must be a key in state_manager.races
    player_2_race: str      # Must be a key in state_manager.races
    player_1_mmr: int
    player_2_mmr: int
    player_1_map_vetoes: List[str]
    player_2_map_vetoes: List[str]
    assigned_at: datetime