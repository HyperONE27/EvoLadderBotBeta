"""
Channel Manager configuration.

All configuration is sourced from environment variables.
"""

import os

from dotenv import load_dotenv

load_dotenv()


# ----------------
# Internal helpers
# ----------------


def _get_str_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Required environment variable {key} not set")
    return value


def _get_int_env(key: str) -> int:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Required environment variable {key} not set")
    return int(value)


# ---------------------
# Environment variables
# ---------------------

DISCORD_BOT_TOKEN: str = _get_str_env("CHANNEL_MANAGER_BOT_TOKEN")

SUPABASE_URL: str = _get_str_env("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY: str = _get_str_env("SUPABASE_SERVICE_ROLE_KEY")

# ---------------------
# Discord infrastructure
# ---------------------

# The guild (server) in which match channels are created.
DISCORD_GUILD_ID: int = _get_int_env("DISCORD_GUILD_ID")

# The category under which match channels are created.
DISCORD_CHANNEL_CATEGORY_ID: int = _get_int_env("DISCORD_CHANNEL_CATEGORY_ID")

# Role IDs that receive VIEW_CHANNEL permission on every match channel
# (e.g. server staff, ladder admins).  Comma-separated snowflakes; may be empty.
DISCORD_STAFF_ROLE_IDS: list[int] = [
    int(r) for r in os.getenv("DISCORD_STAFF_ROLE_IDS", "").split(",") if r.strip()
]

# ---------------------
# Channel lifecycle
# ---------------------

# Seconds to wait before deleting a channel after a match concludes.
# Set via env var; defaults to 0 (immediate).
CHANNEL_DELETION_DELAY_SECONDS: int = int(
    os.getenv("CHANNEL_DELETION_DELAY_SECONDS", "0")
)
