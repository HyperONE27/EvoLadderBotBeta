"""
Channel Manager configuration.

Environment variables are loaded from .env at startup.
Hardcoded Discord infrastructure constants must be filled in before deployment.
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


# ---------------------
# Environment variables
# ---------------------

DISCORD_BOT_TOKEN: str = _get_str_env("CHANNEL_MANAGER_BOT_TOKEN")

SUPABASE_URL: str = _get_str_env("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY: str = _get_str_env("SUPABASE_SERVICE_ROLE_KEY")

# ---------------------
# Discord infrastructure  ← fill these in before deploying
# ---------------------

# The guild (server) in which match channels are created.
DISCORD_GUILD_ID: int = 0  # ← fill in

# The category under which match channels are created.
DISCORD_CHANNEL_CATEGORY_ID: int = 0  # ← fill in

# Role IDs that receive VIEW_CHANNEL permission on every match channel
# (e.g. server staff, ladder admins).  Add as many as needed.
DISCORD_STAFF_ROLE_IDS: list[int] = []  # ← fill in

# ---------------------
# Channel lifecycle
# ---------------------

# Seconds to wait before deleting a channel after a match concludes.
# Set via env var; defaults to 0 (immediate).
CHANNEL_DELETION_DELAY_SECONDS: int = int(
    os.getenv("CHANNEL_DELETION_DELAY_SECONDS", "0")
)
