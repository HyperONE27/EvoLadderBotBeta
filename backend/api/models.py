from pydantic import BaseModel
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


class AdminBanResponse(BaseModel):
    success: bool
    new_is_banned: bool


# --- /admin statusreset ---


class AdminStatusResetRequest(BaseModel):
    discord_uid: int


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


class AdminSnapshotResponse(BaseModel):
    queue: list[QueueEntry1v1]
    active_matches: list[Matches1v1Row]
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


class ProfileResponse(BaseModel):
    player: PlayersRow | None
    mmrs_1v1: list[MMRs1v1Row]


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
