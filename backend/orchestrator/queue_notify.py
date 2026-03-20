"""Eligible subscribers for anonymous queue-activity DMs."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from backend.orchestrator.state import StateManager


def footer_for_cooldown_minutes(minutes: int) -> str:
    return (
        "Per your settings, you will not receive another notification like this for "
        f"{minutes} minute{'s' if minutes != 1 else ''}."
    )


def compute_queue_activity_targets(
    state_manager: StateManager,
    joiner_uid: int,
    game_mode: str,
    last_sent: dict[int, datetime],
    now: datetime,
) -> tuple[list[int], dict[str, str]]:
    """Return subscriber uids and per-uid DM footers; mutates *last_sent* for chosen uids."""

    if game_mode != "1v1":
        return [], {}

    ndf = state_manager.notifications_df
    pdf = state_manager.players_df
    if ndf.is_empty():
        return [], {}

    subs = ndf.filter(pl.col("notify_queue_1v1"))
    if subs.is_empty():
        return [], {}

    joined = subs.join(
        pdf.select(
            "discord_uid",
            "completed_setup",
            "accepted_tos",
            "is_banned",
        ),
        on="discord_uid",
        how="inner",
    )
    joined = joined.filter(
        (pl.col("discord_uid") != joiner_uid)
        & pl.col("completed_setup")
        & pl.col("accepted_tos")
        & ~pl.col("is_banned")
    )

    uids: list[int] = []
    footers: dict[str, str] = {}
    for row in joined.iter_rows(named=True):
        uid = int(row["discord_uid"])
        cd_min = int(row["queue_notify_cooldown_minutes"])
        prev = last_sent.get(uid)
        if prev is not None and (now - prev) < timedelta(minutes=cd_min):
            continue
        uids.append(uid)
        footers[str(uid)] = footer_for_cooldown_minutes(cd_min)
        last_sent[uid] = now
    return uids, footers
