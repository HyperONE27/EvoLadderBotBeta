import os

from dotenv import load_dotenv

from common.config import ALLOW_AI_PLAYERS as ALLOW_AI_PLAYERS
from common.config import CONFIRMATION_TIMEOUT as CONFIRMATION_TIMEOUT
from common.config import CURRENT_SEASON as CURRENT_SEASON
from common.config import ENABLE_REPLAY_VALIDATION as ENABLE_REPLAY_VALIDATION
from common.config import (
    EXCLUDE_INACTIVE_PLAYERS_FROM_LETTER as EXCLUDE_INACTIVE_PLAYERS_FROM_LETTER,
)
from common.config import EXPECTED_LOBBY_SETTINGS as EXPECTED_LOBBY_SETTINGS
from common.config import GAME_MODES as GAME_MODES
from common.config import IN_GAME_CHANNEL as IN_GAME_CHANNEL
from common.config import LEADERBOARD_INACTIVITY_DAYS as LEADERBOARD_INACTIVITY_DAYS
from common.config import MAX_MAP_VETOES as MAX_MAP_VETOES
from common.urls import QUICKSTART_URL as QUICKSTART_URL
from common.urls import TOS_MIRROR_URL as TOS_MIRROR_URL
from common.urls import TOS_URL as TOS_URL

load_dotenv()


# ----------------
# Internal helpers
# ----------------


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


# ---------------------
# Season
# ---------------------

# CURRENT_SEASON → common/config.py

# ---------------------
# Environment variables
# ---------------------

DATABASE: dict[str, str] = {
    "url": _get_str_env("SUPABASE_URL"),
    "anon_key": _get_str_env("SUPABASE_ANON_KEY"),
    "service_role_key": _get_str_env("SUPABASE_SERVICE_ROLE_KEY"),
}

STORAGE: dict[str, str] = {
    "bucket_name": _get_str_env("SUPABASE_BUCKET_NAME"),
}

# ---------------------
# Game rules
# ---------------------

# EXPECTED_LOBBY_SETTINGS → common/config.py
# IN_GAME_CHANNEL         → common/config.py
# GAME_MODES              → common/config.py
# MAX_MAP_VETOES          → common/config.py

# ---------------------
# Match lifecycle timing
# ---------------------

# CONFIRMATION_TIMEOUT → common/config.py

# ---------------------
# Matchmaker constants
# ---------------------

MATCHMAKER: dict[str, float | int] = {
    "balance_threshold": 50,
    "refinement_passes": 2,
    "wait_cycle_priority_coefficient": 20,
    "wait_cycle_priority_exponent": 1.25,
}

BASE_MMR_WINDOW: int = 100
MMR_WINDOW_GROWTH_PER_CYCLE: int = 50
WAIT_PRIORITY_COEFFICIENT: float = 20.0
BALANCE_THRESHOLD_MMR: int = 50

# ---------------------
# MMR / ELO
# ---------------------

MMR: dict[str, int] = {
    "default": 1500,
    "divisor": 500,
    "k_factor": 40,
}

# ---------------------
# Queue timing
# ---------------------

QUEUE: dict[str, int] = {
    "abort_interval": 60,
    "activity_interval": 30,
    "expansion_step": 1,
    "match_interval": 60,
}

# ---------------------
# Leaderboard
# ---------------------

# LEADERBOARD_INACTIVITY_DAYS          → common/config.py
# EXCLUDE_INACTIVE_PLAYERS_FROM_LETTER → common/config.py

# ---------------------
# Replay configuration
# ---------------------

REPLAY_WORKER_PROCESSES: int = int(os.getenv("REPLAY_WORKER_PROCESSES", "2"))

# How many minutes after match assignment a replay may have started.
REPLAY_TIMESTAMP_WINDOW_MINUTES: int = 60

# ---------------------
# Feature flags
# ---------------------

# ENABLE_REPLAY_VALIDATION             → common/config.py
# ALLOW_AI_PLAYERS                     → common/config.py

# ---------------------
# URLs
# ---------------------

# QUICKSTART_URL  → common/urls.py
# TOS_URL         → common/urls.py
# TOS_MIRROR_URL  → common/urls.py
