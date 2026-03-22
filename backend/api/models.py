from datetime import datetime

from pydantic import BaseModel, Field

from backend.domain_types.dataframes import (
    AdminsRow,
    Matches1v1Row,
    MMRs1v1Row,
    PlayersRow,
    Preferences1v1Row,
    Replays1v1Row,
)
from backend.domain_types.ephemeral import QueueEntry1v1


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


# --- /admin match ---


class AdminMatchResponse(BaseModel):
    match: Matches1v1Row | None
    player_1: PlayersRow | None
    player_2: PlayersRow | None
    admin: AdminsRow | None
    replays: list[Replays1v1Row]
    verification: list[dict | None]
    replay_urls: list[str | None]


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


class ProfileResponse(BaseModel):
    player: PlayersRow | None
    mmrs_1v1: list[ProfileMmrEntry]


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
    discord_uid: int
    discord_username: str
    bw_race: str | None = None
    sc2_race: str | None = None
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


# --- /preferences_1v1 ---


class Preferences1v1Response(BaseModel):
    preferences: Preferences1v1Row | None


class PreferencesUpsertRequest(BaseModel):
    discord_uid: int
    last_chosen_races: list[str]
    last_chosen_vetoes: list[str]


class PreferencesUpsertResponse(BaseModel):
    success: bool


# --- /queue_1v1/stats ---


class QueueStatsResponse(BaseModel):
    total: int
    bw_only: int
    sc2_only: int
    both: int


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
    notify_queue_2v2: bool
    notify_queue_ffa: bool
    queue_notify_cooldown_minutes: int
    updated_at: str | None = None


class NotificationsUpsertRequest(BaseModel):
    discord_uid: int
    notify_queue_1v1: bool | None = None
    notify_queue_2v2: bool | None = None
    notify_queue_ffa: bool | None = None
    queue_notify_cooldown_minutes: int | None = Field(None, ge=5, le=1440)


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


class PlayerNameAvailabilityResponse(BaseModel):
    available: bool


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
