from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.domain_types.dataframes import (
    AdminsRow,
    Matches1v1Row,
    Matches2v2Row,
    MMRs1v1Row,
    PlayersRow,
    Preferences1v1Row,
    Preferences2v2Row,
    Replays1v1Row,
)
from backend.domain_types.ephemeral import QueueEntry1v1, QueueEntry2v2


class GreetingResponse(BaseModel):
    message: str


# --- /admins/{discord_uid} ---


class AdminsResponse(BaseModel):
    admin: AdminsRow | None


# --- /admin ban ---


class AdminBanRequest(BaseModel):
    discord_uid: int
    admin_discord_uid: int


class AdminBanResponse(BaseModel):
    success: bool
    new_is_banned: bool


# --- /admin statusreset ---


class AdminStatusResetRequest(BaseModel):
    discord_uid: int
    admin_discord_uid: int


class AdminStatusResetResponse(BaseModel):
    success: bool
    error: str | None = None
    old_status: str | None = None


# --- /admin resolve ---


class AdminResolveRequest(BaseModel):
    result: str
    admin_discord_uid: int


class AdminResolveResponse(BaseModel):
    success: bool
    error: str | None = None
    data: dict | None = None


# --- /admin snapshot ---


class ActiveMatchSnapshotRow(BaseModel):
    """``matches_1v1`` row with ranks and ISO nationalities for admin /snapshot."""

    id: int
    player_1_discord_uid: int
    player_2_discord_uid: int
    player_1_name: str
    player_2_name: str
    player_1_race: str
    player_2_race: str
    player_1_mmr: int
    player_2_mmr: int
    player_1_report: str | None = None
    player_2_report: str | None = None
    match_result: str | None = None
    player_1_mmr_change: int | None = None
    player_2_mmr_change: int | None = None
    map_name: str
    server_name: str
    assigned_at: datetime | None = None
    completed_at: datetime | None = None
    admin_intervened: bool
    admin_discord_uid: int | None = None
    player_1_replay_path: str | None = None
    player_1_replay_row_id: int | None = None
    player_1_uploaded_at: datetime | None = None
    player_2_replay_path: str | None = None
    player_2_replay_row_id: int | None = None
    player_2_uploaded_at: datetime | None = None
    player_1_letter_rank: str = "U"
    player_2_letter_rank: str = "U"
    player_1_nationality: str = "--"
    player_2_nationality: str = "--"


class AdminSnapshotResponse(BaseModel):
    queue: list[QueueEntry1v1]
    active_matches: list[ActiveMatchSnapshotRow]
    dataframe_stats: dict


class ActiveMatchSnapshot2v2Row(BaseModel):
    """``matches_2v2`` row enriched with team letter ranks and player nationalities."""

    id: int
    team_1_player_1_discord_uid: int
    team_1_player_2_discord_uid: int
    team_1_player_1_name: str
    team_1_player_2_name: str
    team_1_player_1_race: str
    team_1_player_2_race: str
    team_1_mmr: int
    team_2_player_1_discord_uid: int
    team_2_player_2_discord_uid: int
    team_2_player_1_name: str
    team_2_player_2_name: str
    team_2_player_1_race: str
    team_2_player_2_race: str
    team_2_mmr: int
    match_result: str | None = None
    assigned_at: datetime | None = None
    completed_at: datetime | None = None
    admin_intervened: bool = False
    admin_discord_uid: int | None = None
    team_1_letter_rank: str = "U"
    team_2_letter_rank: str = "U"
    team_1_player_1_nationality: str = "--"
    team_1_player_2_nationality: str = "--"
    team_2_player_1_nationality: str = "--"
    team_2_player_2_nationality: str = "--"


class PartySnapshotRow(BaseModel):
    leader_discord_uid: int
    leader_player_name: str
    leader_nationality: str = "--"
    member_discord_uid: int
    member_player_name: str
    member_nationality: str = "--"
    created_at: datetime


class AdminSnapshot2v2Response(BaseModel):
    queue: list[QueueEntry2v2]
    active_matches: list[ActiveMatchSnapshot2v2Row]
    parties: list[PartySnapshotRow]
    dataframe_stats: dict


# --- /admin match ---


class AdminMatchResponse(BaseModel):
    match: Matches1v1Row | None
    player_1: PlayersRow | None
    player_2: PlayersRow | None
    admin: AdminsRow | None
    replays: list[Replays1v1Row]
    verification: list[dict | None]
    replay_urls: list[str | None]


class AdminMatch2v2Response(BaseModel):
    match: Matches2v2Row | None
    team_1_player_1: PlayersRow | None
    team_1_player_2: PlayersRow | None
    team_2_player_1: PlayersRow | None
    team_2_player_2: PlayersRow | None
    admin: AdminsRow | None


# --- /owner admin ---


class OwnerToggleAdminRequest(BaseModel):
    discord_uid: int
    discord_username: str
    owner_discord_uid: int


class OwnerToggleAdminResponse(BaseModel):
    success: bool
    error: str | None = None
    action: str | None = None
    new_role: str | None = None


# --- /owner mmr ---


class OwnerSetMMRRequest(BaseModel):
    discord_uid: int
    race: str
    new_mmr: int
    owner_discord_uid: int


class OwnerSetMMRResponse(BaseModel):
    success: bool
    old_mmr: int | None = None


# --- /help ---

# --- /leaderboard ---


class LeaderboardEntry(BaseModel):
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
    last_played_at: str | None


class LeaderboardResponse(BaseModel):
    leaderboard: list[LeaderboardEntry]


class LeaderboardEntry2v2Model(BaseModel):
    player_1_discord_uid: int
    player_2_discord_uid: int
    player_1_name: str
    player_2_name: str
    player_1_nationality: str
    player_2_nationality: str
    ordinal_rank: int
    active_ordinal_rank: int
    letter_rank: str
    mmr: int
    games_played: int
    games_won: int
    games_lost: int
    games_drawn: int
    last_played_at: str | None


class LeaderboardResponse2v2(BaseModel):
    leaderboard: list[LeaderboardEntry2v2Model]


# --- /profile ---


class ProfilePeriodStats(BaseModel):
    games_played: int = 0
    games_won: int = 0
    games_lost: int = 0
    games_drawn: int = 0


class ProfileMmrEntry(BaseModel):
    id: int
    discord_uid: int
    player_name: str
    race: str
    mmr: int
    games_played: int
    games_won: int
    games_lost: int
    games_drawn: int
    last_played_at: datetime | None = None
    letter_rank: str = "U"
    recent: dict[str, ProfilePeriodStats] = Field(default_factory=dict)


class Profile2v2PartnerEntry(BaseModel):
    partner_discord_uid: int
    partner_player_name: str
    mmr: int
    games_played: int
    games_won: int
    games_lost: int
    games_drawn: int
    last_played_at: datetime | None = None
    recent: dict[str, ProfilePeriodStats] = Field(default_factory=dict)


class ProfileResponse(BaseModel):
    player: PlayersRow | None
    mmrs_1v1: list[ProfileMmrEntry]
    mmrs_2v2: list[Profile2v2PartnerEntry] = Field(default_factory=list)
    notifications: NotificationsOut | None = None


# --- /prune ---

# --- /queue ---


class QueueJoinRequest(BaseModel):
    discord_uid: int
    discord_username: str
    bw_race: str | None = None
    sc2_race: str | None = None
    bw_mmr: int | None = None
    sc2_mmr: int | None = None
    map_vetoes: list[str] = []


class QueueJoinResponse(BaseModel):
    success: bool
    message: str | None


class QueueLeaveRequest(BaseModel):
    discord_uid: int


class QueueLeaveResponse(BaseModel):
    success: bool
    message: str | None


class Queue2v2JoinRequest(BaseModel):
    """Queue join request — submitted by the party leader on behalf of the team.

    At least one composition must be fully declared (both race fields non-None).
    The BW + SC2 comp, if declared, must cover different eras (one bw_*, one sc2_*).
    """

    discord_uid: int  # leader only
    discord_username: str
    pure_bw_leader_race: str | None = None
    pure_bw_member_race: str | None = None
    mixed_leader_race: str | None = None
    mixed_member_race: str | None = None
    pure_sc2_leader_race: str | None = None
    pure_sc2_member_race: str | None = None
    map_vetoes: list[str] = []


class Queue2v2JoinResponse(BaseModel):
    success: bool
    message: str | None


class Queue2v2LeaveRequest(BaseModel):
    discord_uid: int


class Queue2v2LeaveResponse(BaseModel):
    success: bool
    message: str | None


# --- /matches_1v1 actions ---


class MatchConfirmRequest(BaseModel):
    discord_uid: int


class MatchConfirmResponse(BaseModel):
    success: bool
    both_confirmed: bool


class MatchAbortRequest(BaseModel):
    discord_uid: int


class MatchAbortResponse(BaseModel):
    success: bool
    message: str | None


class MatchReportRequest(BaseModel):
    discord_uid: int
    report: str


class MatchReportResponse(BaseModel):
    success: bool
    message: str | None
    match: Matches1v1Row | None = None


# --- /matches_2v2 actions ---


class Match2v2ConfirmRequest(BaseModel):
    discord_uid: int


class Match2v2ConfirmResponse(BaseModel):
    success: bool
    all_confirmed: bool


class Match2v2AbortRequest(BaseModel):
    discord_uid: int


class Match2v2AbortResponse(BaseModel):
    success: bool
    message: str | None


class Match2v2ReportRequest(BaseModel):
    discord_uid: int
    report: str  # "team_1_win" | "team_2_win" | "draw"


class Match2v2ReportResponse(BaseModel):
    success: bool
    message: str | None
    match: Matches2v2Row | None = None


# --- /preferences_1v1 ---


class Preferences1v1Response(BaseModel):
    preferences: Preferences1v1Row | None


class PreferencesUpsertRequest(BaseModel):
    discord_uid: int
    last_chosen_races: list[str]
    last_chosen_vetoes: list[str]


class PreferencesUpsertResponse(BaseModel):
    success: bool


# --- /preferences_2v2 ---


class Preferences2v2Response(BaseModel):
    preferences: Preferences2v2Row | None


class Preferences2v2UpsertRequest(BaseModel):
    discord_uid: int
    last_pure_bw_leader_race: str | None = None
    last_pure_bw_member_race: str | None = None
    last_mixed_leader_race: str | None = None
    last_mixed_member_race: str | None = None
    last_pure_sc2_leader_race: str | None = None
    last_pure_sc2_member_race: str | None = None
    last_chosen_vetoes: list[str] = []


class Preferences2v2UpsertResponse(BaseModel):
    success: bool


# --- /queue_1v1/stats ---


class QueueStatsResponse(BaseModel):
    total: int
    bw_only: int
    sc2_only: int
    both: int


class Queue2v2StatsResponse(BaseModel):
    total: int
    bw_only: int
    mixed_only: int
    sc2_only: int
    bw_mixed: int
    bw_sc2: int
    mixed_sc2: int
    all_three: int


# --- /analytics/queue_joins ---


class QueueJoinAnalyticsBucket(BaseModel):
    t: str
    count: int


class QueueJoinAnalyticsResponse(BaseModel):
    game_mode: str
    bucket_minutes: int
    dedupe: bool
    buckets: list[QueueJoinAnalyticsBucket]


# --- /notifications ---


class NotificationsOut(BaseModel):
    id: int
    discord_uid: int
    read_quick_start_guide: bool
    notify_queue_1v1: bool
    notify_queue_1v1_cooldown: int
    notify_queue_1v1_last_sent: str | None = None
    notify_queue_2v2: bool
    notify_queue_2v2_cooldown: int
    notify_queue_2v2_last_sent: str | None = None
    notify_queue_ffa: bool
    notify_queue_ffa_cooldown: int
    notify_queue_ffa_last_sent: str | None = None
    updated_at: str | None = None


class NotificationsUpsertRequest(BaseModel):
    discord_uid: int
    notify_queue_1v1: bool | None = None
    notify_queue_2v2: bool | None = None
    notify_queue_ffa: bool | None = None
    notify_queue_1v1_cooldown: int | None = Field(None, ge=5, le=1440)
    notify_queue_2v2_cooldown: int | None = Field(None, ge=5, le=1440)
    notify_queue_ffa_cooldown: int | None = Field(None, ge=5, le=1440)


# --- /setcountry ---


class SetCountryConfirmRequest(BaseModel):
    discord_uid: int
    discord_username: str
    country_code: str


class SetCountryConfirmResponse(BaseModel):
    success: bool
    message: str | None


# --- /setup ---


class SetupConfirmRequest(BaseModel):
    discord_uid: int
    discord_username: str
    player_name: str
    alt_player_names: list[str] | None
    battletag: str
    nationality: str
    location: str
    language: str


class SetupConfirmResponse(BaseModel):
    success: bool
    message: str | None


# --- /termsofservice ---


class TermsOfServiceConfirmRequest(BaseModel):
    discord_uid: int
    discord_username: str
    accepted: bool


class TermsOfServiceConfirmResponse(BaseModel):
    success: bool
    message: str | None


# --- General endpoints ---


class PlayersResponse(BaseModel):
    player: PlayersRow | None


class PlayerRegisterRequest(BaseModel):
    discord_uid: int
    discord_username: str


class PlayerRegisterResponse(BaseModel):
    created: bool


class PlayerNameAvailabilityResponse(BaseModel):
    available: bool


class ToggleLobbyGuideResponse(BaseModel):
    success: bool
    new_value: bool


class Matches1v1Response(BaseModel):
    match: Matches1v1Row | None


class MMRs1v1Response(BaseModel):
    mmr: MMRs1v1Row | None


class MMRs1v1AllResponse(BaseModel):
    mmrs: list[MMRs1v1Row]


# --- /replays_1v1 ---


class ReplayUploadResponse(BaseModel):
    success: bool
    error: str | None = None
    parsed: dict | None = None
    verification: dict | None = None
    replay_id: int | None = None
    upload_status: str | None = None
    auto_resolved: bool = False
    match: dict | None = None


# --- /party_2v2 ---


class PartyInviteRequest(BaseModel):
    inviter_discord_uid: int
    inviter_player_name: str
    invitee_discord_uid: int
    invitee_player_name: str


class PartyInviteResponse(BaseModel):
    success: bool
    error: str | None = None


class PartyRespondRequest(BaseModel):
    invitee_discord_uid: int
    accepted: bool


class PartyRespondResponse(BaseModel):
    success: bool
    error: str | None = None
    inviter_discord_uid: int | None = None
    inviter_player_name: str | None = None
    invitee_discord_uid: int | None = None
    invitee_player_name: str | None = None


class PartyLeaveRequest(BaseModel):
    discord_uid: int


class PartyLeaveResponse(BaseModel):
    success: bool
    error: str | None = None
    partner_discord_uid: int | None = None


class PartyInfoResponse(BaseModel):
    in_party: bool
    leader_discord_uid: int | None = None
    leader_player_name: str | None = None
    member_discord_uid: int | None = None
    member_player_name: str | None = None
    created_at: datetime | None = None
