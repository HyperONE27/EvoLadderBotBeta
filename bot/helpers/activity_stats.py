"""Compute summary statistics from queue-join analytics buckets.

Used by the /activity command to populate embed fields alongside the chart image.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from common.i18n import t

# Weekday index 0=Monday … 6=Sunday  →  i18n day key
_DAY_KEYS = [
    "day.mon",
    "day.tue",
    "day.wed",
    "day.thu",
    "day.fri",
    "day.sat",
    "day.sun",
]

_RANGE_DAYS = {"24h": 1, "7d": 7, "30d": 30}

# Hangul Filler — renders as blank but satisfies Discord's non-empty field name
# requirement.  Same trick used in MatchInfoEmbed.
_BLANK = "\u3164"


def _parse_buckets(buckets: list[dict]) -> list[tuple[datetime, int]]:
    out: list[tuple[datetime, int]] = []
    for b in buckets:
        raw = b["t"]
        if isinstance(raw, str):
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            dt = raw
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        out.append((dt, int(b["count"])))
    return out


def _day_name(weekday: int, locale: str) -> str:
    return t(_DAY_KEYS[weekday], locale)


def _fmt_avg(avg: float) -> str:
    """Integer when ≥ 10, one decimal below that."""
    return str(int(round(avg))) if avg >= 10 else f"{avg:.1f}"


def build_activity_embed_fields(
    buckets: list[dict],
    range_key: str,
    locale: str,
) -> list[tuple[str, str, bool]]:
    """Return a list of ``(name, value, inline)`` tuples ready for embed.add_field().

    range_key: "24h" | "7d" | "30d"
    """
    if not buckets:
        return []

    parsed = _parse_buckets(buckets)
    total = sum(c for _, c in parsed)

    if range_key == "24h":
        peak_dt, peak_count = max(parsed, key=lambda x: x[1])
        peak_value = (
            f"{_day_name(peak_dt.weekday(), locale)} {peak_dt.strftime('%H:00')} UTC"
            f" · **{peak_count}**"
        )

        max_t = max(dt for dt, _ in parsed)
        cutoff = max_t - timedelta(hours=3)
        last3h = sum(c for dt, c in parsed if dt >= cutoff)

        return [
            (t("activity_stats.total.name", locale), str(total), True),
            (t("activity_stats.peak.name", locale), peak_value, True),
            (t("activity_stats.last3h.name", locale), str(last3h), True),
        ]

    # 7d / 30d ---------------------------------------------------------------

    # Compute avg joins per (weekday, hour) slot.
    day_hour_sums: dict[tuple[int, int], int] = defaultdict(int)
    day_hour_counts: dict[tuple[int, int], int] = defaultdict(int)
    for dt, count in parsed:
        slot = (dt.weekday(), dt.hour)
        day_hour_sums[slot] += count
        day_hour_counts[slot] += 1

    averages: dict[tuple[int, int], float] = {
        k: day_hour_sums[k] / day_hour_counts[k] for k in day_hour_sums
    }

    # Best window (hour) per day of week.
    best_per_day: dict[int, tuple[int, float]] = {}  # weekday → (hour, avg)
    for (wday, hour), avg in averages.items():
        if wday not in best_per_day or avg > best_per_day[wday][1]:
            best_per_day[wday] = (hour, avg)

    # Sort days busiest-first.
    sorted_days = sorted(best_per_day.items(), key=lambda x: x[1][1], reverse=True)

    lines = [
        f"{i + 1}. {_day_name(wday, locale)}: {hour:02d}:00 UTC"
        f" · **{t('activity_stats.window.avg', locale, avg=_fmt_avg(avg))}**"
        for i, (wday, (hour, avg)) in enumerate(sorted_days)
    ]

    # Row 1 (2 inline): Total | Avg/Day
    range_days = _RANGE_DAYS.get(range_key, 1)
    avg_per_day = total / range_days

    # Row 2 (2 inline): Peak Per Day — top 4 in col 1, remaining in col 2.
    col1 = "\n".join(lines[:4]) if lines[:4] else _BLANK
    col2 = "\n".join(lines[4:]) if lines[4:] else _BLANK

    return [
        (t("activity_stats.total.name", locale), str(total), True),
        (t("activity_stats.avg_per_day.name", locale), _fmt_avg(avg_per_day), True),
        # Zero-width space separator forces a new inline row below.
        ("\u200b", "\u200b", False),
        (t("activity_stats.windows.name", locale), col1, True),
        (_BLANK, col2, True),
    ]
