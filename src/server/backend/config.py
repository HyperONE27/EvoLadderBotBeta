import json
import os
from dotenv import load_dotenv
from typing import cast, TypedDict

load_dotenv()

# Type-checking around loading environment variables


class Admin(TypedDict):
    discord_id: int
    name: str
    role: str


def _get_admins_env(key: str) -> list[Admin]:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Required environment variable {key} not set")
    data = json.loads(value)
    return cast(list[Admin], data)


def _get_int_env(key: str) -> int:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Required environment variable {key} not set")
    return int(value)


def _get_str_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Required environment variable {key} not set")
    return value


# Environment variables

ADMINS: list[Admin] = _get_admins_env("ADMINS")

DATABASE: dict[str, str] = {
    "url": _get_str_env("SUPABASE_URL"),
    "anon_key": _get_str_env("SUPABASE_ANON_KEY"),
    "service_role_key": _get_str_env("SUPABASE_SERVICE_ROLE_KEY"),
}

DISCORD: dict[str, (int | str)] = {
    "bot_token": _get_str_env("BOT_TOKEN"),
    "match_log_channel_id": _get_int_env("MATCH_LOG_CHANNEL_ID"),
}

STORAGE: dict[str, str] = {
    "bucket_name": _get_str_env("SUPABASE_BUCKET_NAME"),
}

# Application constants

EXPECTED_LOBBY_SETTINGS: dict[str, str] = {
    "duration": "Infinite",
    "locked_alliances": "Yes",
    "privacy": "Normal",
    "speed": "Faster",
}

MATCHMAKER: dict[str, (float | int)] = {
    "balance_threshold": 50,
    "refinement_passes": 2,
    "wait_cycle_priority_coefficient": 20,
    "wait_cycle_priority_exponent": 1.25,
}

MMR: dict[str, int] = {"default": 1500, "divisor": 500, "k_factor": 40}

QUEUE: dict[str, int] = {
    "abort_interval": 60,
    "activity_interval": 30,
    "expansion_step": 1,
    "match_interval": 45,
}

# Other constants

CURRENT_SEASON: str = "season_alpha"
