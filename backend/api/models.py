from pydantic import BaseModel
from backend.domain_types.dataframes import (
    Matches1v1Row,
    MMRs1v1Row,
    PlayersRow,
    Preferences1v1Row,
)


class GreetingResponse(BaseModel):
    message: str


# --- /owner admin ---

# --- /owner mmr ---

# --- /owner profile ---

# --- /admin ban ---

# --- /admin match ---

# --- /admin profile ---

# --- /admin resolve ---

# --- /admin snapshot ---

# --- /admin status ---

# --- /help ---

# --- /leaderboard ---


class LeaderboardRequest(BaseModel):
    discord_uid: int
    game_mode: str


class LeaderboardResponse(BaseModel):
    pass


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


class SetupInitRequest(BaseModel):
    discord_uid: int
    discord_username: str


class SetupInitResponse(BaseModel):
    player_name: str | None
    alt_player_names: list[str] | None
    battletag: str | None
    nationality: str | None
    location: str | None
    language: str | None


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
