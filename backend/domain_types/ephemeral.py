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


# ---------------------------------------------------------------------------
# 2v2 party types
# ---------------------------------------------------------------------------


class PendingPartyInvite2v2(TypedDict):
    inviter_discord_uid: int
    inviter_player_name: str
    invitee_discord_uid: int
    invitee_player_name: str
    invited_at: datetime


class PartyEntry2v2(TypedDict):
    leader_discord_uid: int
    leader_player_name: str
    member_discord_uid: int
    member_player_name: str
    created_at: datetime


# ---------------------------------------------------------------------------
# 2v2 queue / matchmaking types
# ---------------------------------------------------------------------------


class QueueEntry2v2(TypedDict):
    discord_uid: int
    player_name: str
    party_partner_discord_uid: int
    bw_race: str | None
    sc2_race: str | None
    nationality: str  # ISO country code; guaranteed set by /setup gate
    location: str | None  # geographic region code for server selection
    team_mmr: int  # pair MMR from mmrs_2v2, looked up at queue-join time
    team_letter_rank: str  # from 2v2 leaderboard; "U" if unranked
    map_vetoes: list[str]
    joined_at: datetime
    wait_cycles: int


class QueueEntry2v2Team(TypedDict):
    """Formed by the matchmaker from two paired QueueEntry2v2 objects.

    Internal to the matchmaker; never stored in StateManager.
    """

    player_1_discord_uid: int
    player_2_discord_uid: int
    player_1_name: str
    player_2_name: str
    player_1_bw_race: str | None
    player_1_sc2_race: str | None
    player_2_bw_race: str | None
    player_2_sc2_race: str | None
    player_1_nationality: str
    player_2_nationality: str
    player_1_location: str | None
    player_2_location: str | None
    team_mmr: int
    team_letter_rank: str
    map_vetoes: list[str]  # union of both players' vetoes
    joined_at: datetime  # earlier of the two join timestamps
    wait_cycles: int  # max of the two wait_cycles values


class MatchCandidate2v2(TypedDict):
    team_1_player_1_discord_uid: int
    team_1_player_2_discord_uid: int
    team_1_player_1_name: str
    team_1_player_2_name: str
    team_1_player_1_race: str  # specific race assigned for this match
    team_1_player_2_race: str
    team_1_player_1_nationality: str
    team_1_player_2_nationality: str
    team_1_player_1_location: str | None
    team_1_player_2_location: str | None
    team_1_mmr: int
    team_1_letter_rank: str
    team_1_map_vetoes: list[str]
    team_2_player_1_discord_uid: int
    team_2_player_2_discord_uid: int
    team_2_player_1_name: str
    team_2_player_2_name: str
    team_2_player_1_race: str
    team_2_player_2_race: str
    team_2_player_1_nationality: str
    team_2_player_2_nationality: str
    team_2_player_1_location: str | None
    team_2_player_2_location: str | None
    team_2_mmr: int
    team_2_letter_rank: str
    team_2_map_vetoes: list[str]


class MatchParams2v2(TypedDict):
    map_name: str
    server_name: str
    in_game_channel: str


# ---------------------------------------------------------------------------
# 2v2 leaderboard
# ---------------------------------------------------------------------------


class LeaderboardEntry2v2(TypedDict):
    player_1_discord_uid: int  # smaller UID (normalized)
    player_2_discord_uid: int  # larger UID (normalized)
    player_1_name: str
    player_2_name: str
    ordinal_rank: int
    active_ordinal_rank: int
    letter_rank: str
    mmr: int
    games_played: int
    games_won: int
    games_lost: int
    games_drawn: int
    last_played_at: datetime
