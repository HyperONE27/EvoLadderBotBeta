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
    ("FFA", "ffa"),
]

MAX_MAP_VETOES: int = 4

# ---------------------------------------------------------------------------
# Match lifecycle timing (seconds)
# ---------------------------------------------------------------------------

CONFIRMATION_TIMEOUT: int = 60

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

ENABLE_REPLAY_VALIDATION: bool = True

ALLOW_AI_PLAYERS: bool = True
