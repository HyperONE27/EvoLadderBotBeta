"""Eligible subscribers for anonymous queue-activity DMs."""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.lookups.notification_lookups import get_queue_activity_subscribers
from common.i18n import t


def footer_for_cooldown_minutes(minutes: int, locale: str = "enUS") -> str:
    suffix = "s" if minutes != 1 else ""
    return t(
        "queue_notify.footer.cooldown.1",
        locale,
        minutes=str(minutes),
        suffix=suffix,
    )


def compute_queue_activity_targets(
    joiner_uid: int,
    game_mode: str,
    last_sent: dict[int, datetime],
    now: datetime,
) -> tuple[list[int], dict[str, str], dict[str, str]]:
    """Return (uids, footers, locales); mutates *last_sent* for chosen uids."""

    eligible = get_queue_activity_subscribers(joiner_uid, game_mode)
    if eligible.is_empty():
        return [], {}, {}

    uids: list[int] = []
    footers: dict[str, str] = {}
    locales: dict[str, str] = {}
    for row in eligible.iter_rows(named=True):
        uid = int(row["discord_uid"])
        if game_mode == "2v2":
            cd_min = int(row["notify_queue_2v2_cooldown"])
        elif game_mode == "FFA":
            cd_min = int(row["notify_queue_ffa_cooldown"])
        else:
            cd_min = int(row["notify_queue_1v1_cooldown"])
        prev = last_sent.get(uid)
        if prev is not None and (now - prev) < timedelta(minutes=cd_min):
            continue
        locale = str(row.get("language", "enUS"))
        uids.append(uid)
        footers[str(uid)] = footer_for_cooldown_minutes(cd_min, locale)
        locales[str(uid)] = locale
        last_sent[uid] = now
    return uids, footers, locales
