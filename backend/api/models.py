from pydantic import BaseModel


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
    country_name: str


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


class SetupConfirmRequest(BaseModel):
    discord_uid: int
    discord_username: str
    player_name: str
    alt_player_names: list[str] | None
    battletag: str
    nationality: str
    location: str


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
