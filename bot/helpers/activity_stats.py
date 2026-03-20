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
            f" ({peak_count})"
        )

        max_t = max(dt for dt, _ in parsed)
        cutoff = max_t - timedelta(hours=3)
        last3h = sum(c for dt, c in parsed if dt >= cutoff)

        return [
            (t("activity_stats.total.name", locale), str(total), True),
            (t("activity_stats.peak.name", locale), peak_value, True),
            (t("activity_stats.last3h.name", locale), str(last3h), True),
        ]

    # 7d / 30d: best window per day of week, sorted by that day's peak avg descending.
    day_hour_sums: dict[tuple[int, int], int] = defaultdict(int)
    day_hour_counts: dict[tuple[int, int], int] = defaultdict(int)
    for dt, count in parsed:
        slot = (dt.weekday(), dt.hour)
        day_hour_sums[slot] += count
        day_hour_counts[slot] += 1

    averages: dict[tuple[int, int], float] = {
        k: day_hour_sums[k] / day_hour_counts[k] for k in day_hour_sums
    }

    # For each weekday that appears in the data, find its peak hour.
    best_per_day: dict[int, tuple[int, float]] = {}  # weekday → (hour, avg)
    for (wday, hour), avg in averages.items():
        if wday not in best_per_day or avg > best_per_day[wday][1]:
            best_per_day[wday] = (hour, avg)

    # Sort days by their peak avg descending (busiest day first).
    sorted_days = sorted(best_per_day.items(), key=lambda x: x[1][1], reverse=True)

    lines = [
        f"{_day_name(wday, locale)} {hour:02d}:00 UTC"
        f" · {t('activity_stats.window.avg', locale, avg=f'{avg:.1f}')}"
        for wday, (hour, avg) in sorted_days
    ]

    return [
        (t("activity_stats.total.name", locale), str(total), True),
        (
            t("activity_stats.windows.name", locale),
            "\n".join(lines) if lines else "—",
            False,
        ),
    ]
