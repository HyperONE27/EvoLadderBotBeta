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
    """One entry per party, created by the party leader.

    Each entry represents a complete team of two.  The leader (discord_uid /
    player_name) is always player_1; the member (party_member_*) is always
    player_2.  This convention is preserved through MatchCandidate2v2 and into
    the matches_2v2 row.

    Race preferences are expressed as three optional team compositions.  A
    composition is "declared" when both of its race fields are non-None.  The
    application enforces that each declared comp has both fields set, and that
    at least one comp is declared.  The mixed comp additionally requires that
    the two races come from different eras (one bw_*, one sc2_*).

    Only the leader queues; the member's player_status is set to 'queueing' by
    the join transition and back to 'in_party' by the leave transition.
    """

    discord_uid: int  # leader
    player_name: str  # leader
    party_member_discord_uid: int
    party_member_name: str
    # Optional team compositions — at least one must be declared (both fields non-None)
    pure_bw_leader_race: str | None
    pure_bw_member_race: str | None
    mixed_leader_race: str | None
    mixed_member_race: str | None
    pure_sc2_leader_race: str | None
    pure_sc2_member_race: str | None
    # Both players' geo data for server selection
    nationality: str  # leader's ISO country code
    location: str | None  # leader's geographic region code
    member_nationality: str
    member_location: str | None
    team_mmr: int  # pair MMR from mmrs_2v2, looked up at queue-join time
    team_letter_rank: str  # from 2v2 leaderboard; "U" if unranked
    map_vetoes: list[str]  # leader's vetoes only; member has no separate input
    joined_at: datetime
    wait_cycles: int


class MatchCandidate2v2(TypedDict):
    """Output of the 2v2 matchmaker.

    player_1 on each team is the party leader (maps from QueueEntry2v2.discord_uid);
    player_2 is the party member (maps from QueueEntry2v2.party_member_discord_uid).
    Races are the specific values drawn from whichever team composition was chosen
    during pool assignment — not preferences, but the resolved race for this match.
    """

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
