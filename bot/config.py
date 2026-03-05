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

BACKEND_URL: str = _get_str_env("BACKEND_URL")

BOT_TOKEN: str = _get_str_env("BOT_TOKEN")
