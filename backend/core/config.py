import os
from dotenv import load_dotenv

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
# Re-exports from common
# ---------------------

from common.config import ALLOW_AI_PLAYERS as ALLOW_AI_PLAYERS  # noqa: E402
from common.config import CONFIRMATION_TIMEOUT as CONFIRMATION_TIMEOUT  # noqa: E402
from common.config import CURRENT_SEASON as CURRENT_SEASON  # noqa: E402
from common.config import ENABLE_REPLAY_VALIDATION as ENABLE_REPLAY_VALIDATION  # noqa: E402
from common.config import EXPECTED_LOBBY_SETTINGS as EXPECTED_LOBBY_SETTINGS  # noqa: E402
from common.config import GAME_MODES as GAME_MODES  # noqa: E402
from common.config import IN_GAME_CHANNEL as IN_GAME_CHANNEL  # noqa: E402
from common.config import LEADERBOARD_INACTIVITY_DAYS as LEADERBOARD_INACTIVITY_DAYS  # noqa: E402
from common.config import MAX_MAP_VETOES as MAX_MAP_VETOES  # noqa: E402
from common.urls import QUICKSTART_URL as QUICKSTART_URL  # noqa: E402
from common.urls import TOS_MIRROR_URL as TOS_MIRROR_URL  # noqa: E402
from common.urls import TOS_URL as TOS_URL  # noqa: E402

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
# Replay configuration
# ---------------------

REPLAY_WORKER_PROCESSES: int = int(os.getenv("REPLAY_WORKER_PROCESSES", "2"))

# How many minutes after match assignment a replay may have started.
REPLAY_TIMESTAMP_WINDOW_MINUTES: int = 60
