from pydantic import BaseModel
from backend.domain_types.dataframes import (
    Matches1v1Row,
    MMRs1v1Row,
    PlayersRow,
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

# --- /prune ---

# --- /queue ---

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
