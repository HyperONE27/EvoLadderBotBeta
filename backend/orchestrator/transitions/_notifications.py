"""Notifications preferences (queue activity DMs)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import structlog

if TYPE_CHECKING:
    from backend.orchestrator.transitions import TransitionManager

logger = structlog.get_logger(__name__)


def ensure_notification_row(self: TransitionManager, discord_uid: int) -> dict:
    """Return the notifications row for *discord_uid*, creating it if missing."""

    ndf = self._state_manager.notifications_df
    hit = ndf.filter(pl.col("discord_uid") == discord_uid)
    if not hit.is_empty():
        return hit.row(0, named=True)

    try:
        created = self._db_writer.insert_notification_row(discord_uid)
    except Exception as exc:
        logger.warning(
            "insert_notification_row failed; fetching existing",
            discord_uid=discord_uid,
            error=str(exc),
        )
        fetched = self._db_writer.fetch_notification_by_discord_uid(discord_uid)
        if fetched is None:
            raise
        created = fetched

    self._state_manager.notifications_df = ndf.vstack(
        pl.DataFrame([created]).cast(ndf.schema)
    )
    return self._state_manager.notifications_df.filter(
        pl.col("discord_uid") == discord_uid
    ).row(0, named=True)


def _replace_notifications_row(self: TransitionManager, row: dict) -> None:
    df = self._state_manager.notifications_df
    uid = int(row["discord_uid"])
    filtered = df.filter(pl.col("discord_uid") != uid)
    self._state_manager.notifications_df = filtered.vstack(
        pl.DataFrame([row]).cast(df.schema)
    )


def upsert_notifications_preferences(
    self: TransitionManager,
    discord_uid: int,
    *,
    notify_queue_1v1: bool | None = None,
    notify_queue_2v2: bool | None = None,
    notify_queue_ffa: bool | None = None,
    notify_queue_1v1_cooldown: int | None = None,
    notify_queue_2v2_cooldown: int | None = None,
    notify_queue_ffa_cooldown: int | None = None,
) -> dict:
    """Merge preference updates and persist."""

    current = ensure_notification_row(self, discord_uid)
    updated = dict(current)
    if notify_queue_1v1 is not None:
        updated["notify_queue_1v1"] = notify_queue_1v1
    if notify_queue_2v2 is not None:
        updated["notify_queue_2v2"] = notify_queue_2v2
    if notify_queue_ffa is not None:
        updated["notify_queue_ffa"] = notify_queue_ffa
    if notify_queue_1v1_cooldown is not None:
        updated["notify_queue_1v1_cooldown"] = int(notify_queue_1v1_cooldown)
    if notify_queue_2v2_cooldown is not None:
        updated["notify_queue_2v2_cooldown"] = int(notify_queue_2v2_cooldown)
    if notify_queue_ffa_cooldown is not None:
        updated["notify_queue_ffa_cooldown"] = int(notify_queue_ffa_cooldown)

    saved = self._db_writer.upsert_notifications_full_row(updated)
    _replace_notifications_row(self, saved)
    return saved
