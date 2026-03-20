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
        peak_label = (
            f"{_day_name(peak_dt.weekday(), locale)} {peak_dt.strftime('%H:00')} UTC"
        )

        # Last 3h: buckets whose timestamp is within 3h of the latest bucket.
        if parsed:
            max_t = max(dt for dt, _ in parsed)
            cutoff = max_t - timedelta(hours=3)
            last3h = sum(c for dt, c in parsed if dt >= cutoff)
        else:
            last3h = 0

        total_lbl = t("activity_stats.total.label", locale)
        peak_lbl = t("activity_stats.peak.label", locale)
        last3h_lbl = t("activity_stats.last3h.label", locale)
        name = t("activity_stats.field.summary", locale)
        value = (
            f"**{total_lbl}:** {total}"
            f" · **{peak_lbl}:** {peak_label} ({peak_count})"
            f" · **{last3h_lbl}:** {last3h}"
        )
        return [(name, value, False)]

    # 7d / 30d — top 3 windows by (weekday, hour) average.
    window_sums: dict[tuple[int, int], int] = defaultdict(int)
    window_occurrences: dict[tuple[int, int], int] = defaultdict(int)
    for dt, count in parsed:
        key = (dt.weekday(), dt.hour)
        window_sums[key] += count
        window_occurrences[key] += 1

    averages: dict[tuple[int, int], float] = {
        k: window_sums[k] / window_occurrences[k] for k in window_sums
    }
    top3 = sorted(averages, key=lambda k: averages[k], reverse=True)[:3]

    windows_lines = [
        f"{i + 1}. {_day_name(wday, locale)} {hour:02d}:00 UTC"
        f" — {t('activity_stats.window.avg', locale, avg=f'{averages[(wday, hour)]:.1f}')}"
        for i, (wday, hour) in enumerate(top3)
    ]

    fields: list[tuple[str, str, bool]] = [
        (t("activity_stats.total.name", locale), str(total), True),
        (
            t("activity_stats.windows.name", locale),
            "\n".join(windows_lines) if windows_lines else "—",
            True,
        ),
    ]
    return fields
