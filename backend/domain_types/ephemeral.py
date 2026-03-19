from datetime import datetime
from typing import TypedDict


class LeaderboardEntry1v1(TypedDict):
    discord_uid: int
    player_name: str
    ordinal_rank: int
    active_ordinal_rank: int
    letter_rank: str
    race: str
    nationality: str
    mmr: int
    games_played: int
    games_won: int
    games_lost: int
    games_drawn: int
    last_played_at: datetime


class MatchCandidate1v1(TypedDict):
    player_1_discord_uid: int
    player_2_discord_uid: int
    player_1_name: str
    player_2_name: str
    player_1_race: str  # Must be a key in state_manager.races
    player_2_race: str  # Must be a key in state_manager.races
    player_1_mmr: int
    player_2_mmr: int
    player_1_map_vetoes: list[str]
    player_2_map_vetoes: list[str]


class MatchParams1v1(TypedDict):
    map_name: str
    server_name: str
    in_game_channel: str


class QueueEntry1v1(TypedDict):
    discord_uid: int
    player_name: str
    bw_race: (
        str | None
    )  # Must be a key in state_manager.races and state_manager.races[bw_race]["is_bw_race"] must be True
    sc2_race: (
        str | None
    )  # Must be a key in state_manager.races and state_manager.races[sc2_race]["is_sc2_race"] must be True
    bw_mmr: int | None
    sc2_mmr: int | None
    bw_letter_rank: (
        str | None
    )  # "U" if unranked, letter rank from leaderboard otherwise
    sc2_letter_rank: (
        str | None
    )  # "U" if unranked, letter rank from leaderboard otherwise
    nationality: str | None  # ISO country code from player profile
    map_vetoes: list[str]  # Must be a key in state_manager.maps
    joined_at: datetime
    wait_cycles: int
