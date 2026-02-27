import polars as pl

# Polars DataFrame schema for storing PostgreSQL table "players"
PLAYERS_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Int32,
    "discord_uid": pl.Int64,
    "discord_username": pl.String,
    "player_name": pl.String,
    "alt_player_names": pl.List(pl.String),
    "battletag": pl.String,
    "nationality": pl.String,
    "location": pl.String,
    "is_banned": pl.Boolean,
    "accepted_tos": pl.Boolean,
    "accepted_tos_at": pl.Datetime,
    "completed_setup": pl.Boolean,
    "completed_setup_at": pl.Datetime,
    "player_status": pl.String,
    "current_match_mode": pl.String,
    "current_match_id": pl.Int32,
}

NOTIFICATIONS_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Int32,
    "discord_uid": pl.Int64,
    "read_quick_start_guide": pl.Boolean,
}

EVENTS_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Int32,
    "discord_uid": pl.Int64,
    "event_type": pl.String,
    "event_data": pl.String,
    "performed_at": pl.Datetime,
}

MATCHES_1V1_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Int32,
    "player_1_discord_uid": pl.Int64,
    "player_2_discord_uid": pl.Int64,
    "player_1_name": pl.String,
    "player_2_name": pl.String,
    "player_1_race": pl.String,
    "player_2_race": pl.String,
    "player_1_mmr": pl.Int32,
    "player_2_mmr": pl.Int32,
    "player_1_report": pl.String,
    "player_2_report": pl.String,
    "match_result": pl.String,
    "mmr_change": pl.Int32,
    "map_name": pl.String,
    "server_name": pl.String,
    "assigned_at": pl.Datetime,
    "completed_at": pl.Datetime,
    "player_1_replay_path": pl.String,
    "player_1_uploaded_at": pl.Datetime,
    "player_2_replay_path": pl.String,
    "player_2_uploaded_at": pl.Datetime,
}

MMRS_1V1_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Int32,
    "discord_uid": pl.Int64,
    "player_name": pl.String,
    "race": pl.String,
    "mmr": pl.Int32,
    "games_played": pl.Int32,
    "games_won": pl.Int32,
    "games_lost": pl.Int32,
    "games_drawn": pl.Int32,
    "last_played_at": pl.Datetime,
}

PREFERENCES_1V1_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Int32,
    "discord_uid": pl.Int64,
    "last_chosen_races": pl.List(pl.String),
    "last_chosen_vetoes": pl.List(pl.String),
}

REPLAYS_1V1_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Int32,
    "replay_path": pl.String,
    "replay_hash": pl.String,
    "replay_time": pl.Datetime,
    "uploaded_at": pl.Datetime,
    "player_1_name": pl.String,
    "player_2_name": pl.String,
    "player_1_race": pl.String,
    "player_2_race": pl.String,
    "match_result": pl.String,
    "player_1_handle": pl.String,
    "player_2_handle": pl.String,
    "observers": pl.List(pl.String),
    "map_name": pl.String,
    "game_duration": pl.Int32,
    "game_privacy": pl.String,
    "game_speed": pl.String,
    "game_duration_setting": pl.String,
    "locked_alliances": pl.String,
    "cache_handles": pl.List(pl.String),
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