import polars as pl

from datetime import datetime
from typing import TypedDict

# ---------------------
# DataFrame definitions
# ---------------------

ADMINS_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Int16,
    "discord_uid": pl.Int64,
    "discord_username": pl.String,
    "role": pl.String,
    "first_promoted_at": pl.Datetime("us", "utc"),
    "last_promoted_at": pl.Datetime("us", "utc"),
    "last_demoted_at": pl.Datetime("us", "utc"),
}

PLAYERS_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Int64,
    "discord_uid": pl.Int64,
    "discord_username": pl.String,
    "player_name": pl.String,
    "alt_player_names": pl.List(pl.String),
    "battletag": pl.String,
    "nationality": pl.String,
    "location": pl.String,
    "language": pl.String,
    "is_banned": pl.Boolean,
    "accepted_tos": pl.Boolean,
    "accepted_tos_at": pl.Datetime("us", "utc"),
    "completed_setup": pl.Boolean,
    "completed_setup_at": pl.Datetime("us", "utc"),
    "player_status": pl.String,
    "current_match_mode": pl.String,
    "current_match_id": pl.Int64,
}

NOTIFICATIONS_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Int64,
    "discord_uid": pl.Int64,
    "read_quick_start_guide": pl.Boolean,
}

EVENTS_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Int64,
    "discord_uid": pl.Int64,
    "event_type": pl.String,
    "event_data": pl.String,
    "performed_at": pl.Datetime("us", "utc"),
}

MATCHES_1V1_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Int64,
    "player_1_discord_uid": pl.Int64,
    "player_2_discord_uid": pl.Int64,
    "player_1_name": pl.String,
    "player_2_name": pl.String,
    "player_1_race": pl.String,
    "player_2_race": pl.String,
    "player_1_mmr": pl.Int16,
    "player_2_mmr": pl.Int16,
    "player_1_report": pl.String,  # nullable — NULL until player reports
    "player_2_report": pl.String,  # nullable — NULL until player reports
    "match_result": pl.String,  # nullable — NULL until resolved
    "player_1_mmr_change": pl.Int16,
    "player_2_mmr_change": pl.Int16,
    "map_name": pl.String,
    "server_name": pl.String,
    "assigned_at": pl.Datetime("us", "utc"),
    "completed_at": pl.Datetime("us", "utc"),
    "admin_intervened": pl.Boolean,
    "admin_discord_uid": pl.Int64,
    "player_1_replay_path": pl.String,
    "player_1_replay_row_id": pl.Int64,
    "player_1_uploaded_at": pl.Datetime("us", "utc"),
    "player_2_replay_path": pl.String,
    "player_2_replay_row_id": pl.Int64,
    "player_2_uploaded_at": pl.Datetime("us", "utc"),
}

MMRS_1V1_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Int64,
    "discord_uid": pl.Int64,
    "player_name": pl.String,
    "race": pl.String,
    "mmr": pl.Int16,
    "games_played": pl.Int32,
    "games_won": pl.Int32,
    "games_lost": pl.Int32,
    "games_drawn": pl.Int32,
    "last_played_at": pl.Datetime("us", "utc"),
}

PREFERENCES_1V1_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Int64,
    "discord_uid": pl.Int64,
    "last_chosen_races": pl.List(pl.String),
    "last_chosen_vetoes": pl.List(pl.String),
}

REPLAYS_1V1_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Int64,
    "matches_1v1_id": pl.Int64,
    "replay_path": pl.String,
    "replay_hash": pl.String,
    "replay_time": pl.Datetime("us", "utc"),
    "uploaded_at": pl.Datetime("us", "utc"),
    "player_1_name": pl.String,
    "player_2_name": pl.String,
    "player_1_race": pl.String,
    "player_2_race": pl.String,
    "match_result": pl.String,
    "player_1_handle": pl.String,
    "player_2_handle": pl.String,
    "observers": pl.List(pl.String),
    "map_name": pl.String,
    "game_duration_seconds": pl.Int32,
    "game_privacy": pl.String,
    "game_speed": pl.String,
    "game_duration_setting": pl.String,
    "locked_alliances": pl.String,
    "cache_handles": pl.List(pl.String),
    "upload_status": pl.String,
}

TABLE_SCHEMAS: dict[str, dict[str, pl.DataType]] = {
    "players": PLAYERS_SCHEMA,
    "notifications": NOTIFICATIONS_SCHEMA,
    "events": EVENTS_SCHEMA,
    "matches_1v1": MATCHES_1V1_SCHEMA,
    "mmrs_1v1": MMRS_1V1_SCHEMA,
    "preferences_1v1": PREFERENCES_1V1_SCHEMA,
    "replays_1v1": REPLAYS_1V1_SCHEMA,
}

# -------------------
# DataFrame row types
# -------------------

class AdminsRow(TypedDict):
    id: int
    discord_uid: int
    discord_username: str
    role: str
    first_promoted_at: datetime
    last_promoted_at: datetime
    last_demoted_at: datetime | None

class PlayersRow(TypedDict):
    id: int
    discord_uid: int
    discord_username: str
    player_name: str | None
    alt_player_names: list[str] | None
    battletag: str | None
    nationality: str | None
    location: str | None
    language: str
    is_banned: bool
    accepted_tos: bool
    accepted_tos_at: datetime | None
    completed_setup: bool
    completed_setup_at: datetime | None
    player_status: str
    current_match_mode: str | None
    current_match_id: int | None


class NotificationsRow(TypedDict):
    id: int
    discord_uid: int
    read_quick_start_guide: bool


class EventsRow(TypedDict):
    id: int
    discord_uid: int
    event_type: str
    event_data: str
    performed_at: datetime


class Matches1v1Row(TypedDict):
    id: int
    player_1_discord_uid: int
    player_2_discord_uid: int
    player_1_name: str
    player_2_name: str
    player_1_race: str
    player_2_race: str
    player_1_mmr: int
    player_2_mmr: int
    player_1_report: str | None
    player_2_report: str | None
    match_result: str | None
    player_1_mmr_change: int | None
    player_2_mmr_change: int | None
    map_name: str
    server_name: str
    assigned_at: datetime | None
    completed_at: datetime | None
    player_1_replay_path: str | None
    player_1_replay_row_id: int | None
    player_1_uploaded_at: datetime | None
    player_2_replay_path: str | None
    player_2_replay_row_id: int | None
    player_2_uploaded_at: datetime | None


class MMRs1v1Row(TypedDict):
    id: int
    discord_uid: int
    player_name: str
    race: str
    mmr: int
    games_played: int
    games_won: int
    games_lost: int
    games_drawn: int
    last_played_at: datetime


class Preferences1v1Row(TypedDict):
    id: int
    discord_uid: int
    last_chosen_races: list[str] | None
    last_chosen_vetoes: list[str] | None


class Replays1v1Row(TypedDict):
    id: int
    matches_1v1_id: int
    replay_path: str
    replay_hash: str
    replay_time: datetime
    uploaded_at: datetime
    player_1_name: str
    player_2_name: str
    player_1_race: str
    player_2_race: str
    match_result: str
    player_1_handle: str
    player_2_handle: str
    observers: list[str]
    map_name: str
    game_duration_seconds: int
    game_privacy: str
    game_speed: str
    game_duration_setting: str
    locked_alliances: str
    cache_handles: list[str]
    upload_status: str
