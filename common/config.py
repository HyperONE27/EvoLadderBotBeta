"""
Shared configuration constants used by both the backend and bot processes.

Backend modules should import these values via ``backend.core.config``,
and bot modules via ``bot.core.config`` — never directly from this module.
"""

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
# Leaderboard
# ---------------------------------------------------------------------------

LEADERBOARD_INACTIVITY_DAYS: int = 30

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

ENABLE_REPLAY_VALIDATION: bool = True

EXCLUDE_INACTIVE_PLAYERS_FROM_LETTER_RANK: bool = True

ALLOW_AI_PLAYERS: bool = True

# ---------------------------------------------------------------------------
# Queue activity charts (/activity)
# ---------------------------------------------------------------------------

# X-axis bin width for join-attempt line charts (matplotlib / Discord attachment).
ACTIVITY_QUEUE_JOIN_CHART_BUCKET_MINUTES: int = 60

# For future “deduped join attempt” series: minimum seconds between counted
# ``queue_join`` events per (discord_uid, game_mode) unless interrupted by
# ``queue_leave``, match pairing, etc. Raw join counts use no deduplication.
ACTIVITY_QUEUE_JOIN_DEDUPE_SECONDS: int = 60

# Maximum (end - start) for GET /analytics/queue_joins.
ACTIVITY_ANALYTICS_MAX_RANGE_DAYS: int = 90

# ---------------------------------------------------------------------------
# Queue activity notifications (/notifyme)
# ---------------------------------------------------------------------------

# Default cooldown (minutes) for new notification rows and when ``/notifyme`` omits
# an explicit value. Must stay within DB CHECK on ``queue_notify_cooldown_minutes``.
QUEUE_NOTIFY_COOLDOWN_MINUTES_DEFAULT: int = 15
