from typing import Dict
import polars as pl

# Polars DataFrame schema for storing PostgreSQL table "players"
PLAYER_SCHEMA: Dict[str, pl.DataType] = {
    "discord_uid": pl.Int64,
    "discord_username": pl.Utf8,
    "player_name": pl.Utf8,
    "battletag": pl.Utf8,
    "alt_player_name_1": pl.Utf8,
    "alt_player_name_2": pl.Utf8,
    "country": pl.Utf8,
    "region": pl.Utf8,
    "accepted_tos": pl.Boolean,
    "accepted_tos_date": pl.Datetime,
    "completed_setup": pl.Boolean,
    "completed_setup_date": pl.Datetime,
    "activation_code": pl.Utf8,
    "created_at": pl.Datetime,
    "updated_at": pl.Datetime,
    "remaining_aborts": pl.Int32,
    "player_state": pl.Utf8,
    "shield_battery_bug": pl.Boolean,
    "is_banned": pl.Boolean,
    "read_quick_start_guide": pl.Boolean,
}

PLAYER_ACTION_LOG_SCHEMA: Dict[str, pl.DataType] = {
    "discord_uid": pl.Int64,
    "player_name": pl.Utf8,
    "setting_name": pl.Utf8,
    "old_value": pl.Utf8,
    "new_value": pl.Utf8,
    "changed_at": pl.Datetime,
    "changed_by": pl.Utf8,
}

PLAYER_COMMAND_CALL_SCHEMA: Dict[str, pl.DataType] = {
    "discord_uid": pl.Int64,
    "player_name": pl.Utf8,
    "command": pl.Utf8,
    "called_at": pl.Datetime,
}

REPLAY_SCHEMA: Dict[str, pl.DataType] = {
    "replay_path": pl.Utf8,
    "replay_hash": pl.Utf8,
    "replay_date": pl.Datetime,
    "player_1_name": pl.Utf8,
    "player_2_name": pl.Utf8,
    "player_1_race": pl.Utf8,
    "player_2_race": pl.Utf8,
    "result": pl.Int64,
    "player_1_handle": pl.Utf8,
    "player_2_handle": pl.Utf8,
    "observers": pl.Utf8,
    "map_name": pl.Utf8,
    "duration": pl.Int64,
    "uploaded_at": pl.Datetime,
    "game_privacy": pl.Utf8,
    "game_speed": pl.Utf8,
    "game_duration_setting": pl.Utf8,
    "locked_alliances": pl.Utf8,
    "cache_handles": pl.Utf8,
}

MMR_1V1_SCHEMA: Dict[str, pl.DataType] = {
    "discord_uid": pl.Int64,
    "player_name": pl.Utf8,
    "race": pl.Utf8,
    "mmr": pl.Int64,
    "games_played": pl.Int64,
    "games_won": pl.Int64,
    "games_lost": pl.Int64,
    "games_drawn": pl.Int64,
    "last_played": pl.Datetime,
}

MATCH_1V1_SCHEMA: Dict[str, pl.DataType] = {
    "player_1_discord_uid": pl.Int64,
    "player_2_discord_uid": pl.Int64,
    "player_1_race": pl.Utf8,
    "player_2_race": pl.Utf8,
    "player_1_mmr": pl.Int64,
    "player_2_mmr": pl.Int64,
    "player_1_report": pl.Int64,
    "player_2_report": pl.Int64,
    "match_result": pl.Int64,
    "mmr_change": pl.Int64,
    "map_played": pl.Utf8,
    "server_used": pl.Utf8,
    "played_at": pl.Datetime,
    "updated_at": pl.Datetime,
    "player_1_replay_path": pl.Utf8,
    "player_1_replay_time": pl.Datetime,
    "player_2_replay_path": pl.Utf8,
    "player_2_replay_time": pl.Datetime,
}

PREFERENCE_1V1_SCHEMA: Dict[str, pl.DataType] = {
    "discord_uid": pl.Int64,
    "last_chosen_races": pl.Utf8,
    "last_chosen_vetoes": pl.Utf8,
}

ADMIN_ACTION_SCHEMA: Dict[str, pl.DataType] = {
    "admin_discord_uid": pl.Int64,
    "admin_username": pl.Utf8,
    "action_type": pl.Utf8,
    "target_player_uid": pl.Int64,
    "target_match_id": pl.Int64,
    "action_details": pl.Json,
    "reason": pl.Utf8,
    "performed_at": pl.Datetime,
}
