"""Owner operations on the content_creators table (caster library access)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import structlog

from common.datetime_helpers import utc_now

if TYPE_CHECKING:
    from backend.orchestrator.transitions import TransitionManager

logger = structlog.get_logger(__name__)


def add_content_creator(
    self: TransitionManager, discord_uid: int, discord_username: str
) -> dict:
    """Insert a content_creator row. Returns result dict.

    - Already present → idempotent no-op, ``action="already_present"``.
    - New row        → Supabase first, then cache, ``action="added"``.
    """
    df = self._state_manager.content_creators_df
    rows = df.filter(pl.col("discord_uid") == discord_uid)
    if not rows.is_empty():
        return {"success": True, "action": "already_present"}

    now = utc_now()
    created = self._db_writer.insert_content_creator(
        discord_uid=discord_uid,
        discord_username=discord_username,
        first_promoted_at=now,
        last_promoted_at=now,
    )
    self._state_manager.content_creators_df = df.vstack(
        pl.DataFrame([created]).cast(df.schema)
    )
    logger.info(f"Content creator added: {discord_username} ({discord_uid})")
    return {"success": True, "action": "added"}


def remove_content_creator(self: TransitionManager, discord_uid: int) -> dict:
    """Delete a content_creator row. Returns result dict.

    - Not present → idempotent no-op, ``action="not_present"``.
    - Present     → Supabase delete first, then cache drop, ``action="removed"``.
    """
    df = self._state_manager.content_creators_df
    rows = df.filter(pl.col("discord_uid") == discord_uid)
    if rows.is_empty():
        return {"success": True, "action": "not_present"}

    self._db_writer.delete_content_creator(discord_uid)
    self._state_manager.content_creators_df = df.filter(
        pl.col("discord_uid") != discord_uid
    )
    logger.info(f"Content creator removed: {discord_uid}")
    return {"success": True, "action": "removed"}
