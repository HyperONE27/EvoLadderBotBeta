"""
Shared configuration constants used by both the backend and bot processes.

Backend modules should import these values via ``backend.core.config``,
and bot modules via ``bot.core.config`` — never directly from this module.
"""

import os

from dotenv import load_dotenv

load_dotenv()


# ----------------
# Internal helpers
# ----------------


def _get_bool_env(key: str) -> bool:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Required environment variable {key} not set")
    return bool(value)


# ---------------------------------------------------------------------------
# Season
# ---------------------------------------------------------------------------

CURRENT_SEASON: str = "season_alpha"

# ---------------------------------------------------------------------------
# Game rules
# ---------------------------------------------------------------------------

EXPECTED_LOBBY_SETTINGS: dict[str, str] = {
    "duration": "Infinite",
    "locked_alliances": "Yes",
    "privacy": "Normal",
    "speed": "Faster",
}

IN_GAME_CHANNEL: str = "SCEvoLadder"

GAME_MODES: list[tuple[str, str]] = [
    ("1v1", "1v1"),
    ("2v2", "2v2"),
]

MAX_MAP_VETOES: int = 4

# ---------------------------------------------------------------------------
# Match lifecycle timing (seconds)
# ---------------------------------------------------------------------------

CONFIRMATION_TIMEOUT: int = 60

# ---------------------------------------------------------------------------
# Timeout penalties (minutes) — applied after abort / abandon
# ---------------------------------------------------------------------------

ABORT_TIMEOUT_MINUTES: int = 10
ABANDON_TIMEOUT_MINUTES: int = 20

# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

LEADERBOARD_INACTIVITY_DAYS: int = 30

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

ENABLE_REPLAY_VALIDATION: bool = True

EXCLUDE_INACTIVE_PLAYERS_FROM_LETTER_RANK: bool = True

ALLOW_AI_PLAYERS: bool = _get_bool_env("ALLOW_AI_PLAYERS")

COERCE_INDETERMINATE_AS_LOSS: bool = _get_bool_env("COERCE_INDETERMINATE_AS_LOSS")

# ---------------------------------------------------------------------------
# Queue activity charts (/activity)
# ---------------------------------------------------------------------------

# X-axis bin width for join-attempt line charts (matplotlib / Discord attachment).
ACTIVITY_QUEUE_JOIN_CHART_BUCKET_MINUTES: int = 60

# Hours between x-axis tick marks per chart time range.
ACTIVITY_CHART_X_TICK_INTERVAL_HOURS: dict[str, int] = {
    "24h": 3,
    "7d": 6,
    "30d": 24,
}

# Backend bucket size (minutes) requested per chart time range.
ACTIVITY_CHART_BUCKET_MINUTES: dict[str, int] = {
    "24h": 30,
    "7d": 120,
    "30d": 720,
}

# Fixed-window deduplication for /activity charts: each player contributes at
# most one join per (discord_uid, game_mode) per N-minute clock-aligned window
# (e.g. HH:00-HH:05, HH:05-HH:10, …).
ACTIVITY_QUEUE_JOIN_DEDUPE_WINDOW_MINUTES: int = 5

# Maximum (end - start) for GET /analytics/queue_joins.
ACTIVITY_ANALYTICS_MAX_RANGE_DAYS: int = 90

# ---------------------------------------------------------------------------
# Queue activity notifications (/notifyme)
# ---------------------------------------------------------------------------

# Default cooldown (minutes) for new notification rows and when ``/notifyme`` omits
# an explicit value. Must stay within DB CHECK on ``queue_notify_cooldown_minutes``.
QUEUE_NOTIFY_COOLDOWN_MINUTES_DEFAULT: int = 15
