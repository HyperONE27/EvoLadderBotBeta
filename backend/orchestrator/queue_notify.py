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
    now: datetime,
) -> tuple[list[int], dict[str, str], dict[str, str], dict[str, int]]:
    """Return (uids, footers, locales, cooldowns).

    Cooldowns is a {str(uid): cd_min} dict used by the caller to persist
    last_sent timestamps and write the wave event row.
    """

    eligible = get_queue_activity_subscribers(joiner_uid, game_mode)
    if eligible.is_empty():
        return [], {}, {}, {}

    last_sent_col = f"notify_queue_{game_mode.lower()}_last_sent"
    cooldown_col = f"notify_queue_{game_mode.lower()}_cooldown"

    uids: list[int] = []
    footers: dict[str, str] = {}
    locales: dict[str, str] = {}
    cooldowns: dict[str, int] = {}
    for row in eligible.iter_rows(named=True):
        uid = int(row["discord_uid"])
        cd_min = int(row[cooldown_col])
        prev: datetime | None = row.get(last_sent_col)
        if prev is not None and (now - prev) < timedelta(minutes=cd_min):
            continue
        locale = str(row.get("language", "enUS"))
        uid_str = str(uid)
        uids.append(uid)
        footers[uid_str] = footer_for_cooldown_minutes(cd_min, locale)
        locales[uid_str] = locale
        cooldowns[uid_str] = cd_min
    return uids, footers, locales, cooldowns
