import os

from discord import app_commands
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

BACKEND_URL: str = _get_str_env("BACKEND_URL")

BOT_TOKEN: str = _get_str_env("BOT_TOKEN")

MATCH_LOG_CHANNEL_ID: int = _get_int_env("MATCH_LOG_CHANNEL_ID")

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
# Leaderboard
# ---------------------

# EXCLUDE_INACTIVE_PLAYERS_FROM_LETTER → common/config.py

# ---------------------
# Feature flags
# ---------------------

# ENABLE_REPLAY_VALIDATION → common/config.py
# ALLOW_AI_PLAYERS         → common/config.py

# ---------------------
# URLs
# ---------------------

# QUICKSTART_URL  → common/urls.py
# TOS_URL         → common/urls.py
# TOS_MIRROR_URL  → common/urls.py

# ---------------------
# Discord API
# ---------------------

DISCORD_MESSAGE_RATE_LIMIT: int = 40

# ---------------------
# Queue heartbeat
# ---------------------

QUEUE_SEARCHING_HEARTBEAT_SECONDS: int = 45

# ---------------------
# Display limits
# ---------------------

MAX_QUEUE_SLOTS: int = 30
MAX_MATCH_SLOTS: int = 15

# ---------------------
# WebSocket
# ---------------------

WS_RECONNECT_BACKOFF_SECONDS: int = 5

# ---------------------
# Message queue
# ---------------------

MESSAGE_QUEUE_MAX_RETRIES: int = 3

# ---------------------
# Discord UI / Game mode choices
# ---------------------

GAME_MODE_CHOICES: list[app_commands.Choice[str]] = [
    app_commands.Choice(name=name, value=value) for name, value in GAME_MODES
]
