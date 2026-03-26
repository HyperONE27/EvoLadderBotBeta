"""Aggregate ``queue_join`` events into time buckets for /activity charts."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

BucketRow = tuple[datetime, int]


def floor_to_bucket(t: datetime, bucket_minutes: int) -> datetime:
    """UTC bucket start containing *t*."""

    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    else:
        t = t.astimezone(timezone.utc)
    epoch = datetime.fromtimestamp(0, tz=timezone.utc)
    delta = t - epoch
    sec = int(delta.total_seconds())
    step = max(1, bucket_minutes) * 60
    bucket_start_sec = (sec // step) * step
    return epoch + timedelta(seconds=bucket_start_sec)


def bucket_queue_join_counts(
    times: Iterable[datetime],
    range_start: datetime,
    range_end: datetime,
    bucket_minutes: int,
) -> list[BucketRow]:
    """Return ordered (bucket_start_utc, raw_count) covering [range_start, range_end).

    Empty buckets are included with count 0.
    """

    rs = range_start if range_start.tzinfo else range_start.replace(tzinfo=timezone.utc)
    re = range_end if range_end.tzinfo else range_end.replace(tzinfo=timezone.utc)
    if rs.tzinfo:
        rs = rs.astimezone(timezone.utc)
    if re.tzinfo:
        re = re.astimezone(timezone.utc)

    counts: dict[datetime, int] = defaultdict(int)
    for t in times:
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        else:
            t = t.astimezone(timezone.utc)
        if t < rs or t >= re:
            continue
        b = floor_to_bucket(t, bucket_minutes)
        counts[b] += 1

    out: list[BucketRow] = []
    cur = floor_to_bucket(rs, bucket_minutes)
    step = timedelta(minutes=max(1, bucket_minutes))
    while cur < re:
        out.append((cur, counts.get(cur, 0)))
        cur = cur + step
    return out


def dedupe_per_fixed_window(
    events: list[tuple[datetime, int]],
    window_minutes: int,
) -> list[datetime]:
    """Per *discord_uid*, keep at most one join per clock-aligned *window_minutes* slot.

    E.g. with ``window_minutes=5``: slots are HH:00–HH:05, HH:05–HH:10, …
    The first event seen in each (uid, slot) is kept; later ones are dropped.
    Returns the kept timestamps in ascending order.
    """

    seen: set[tuple[int, datetime]] = set()
    result: list[datetime] = []

    for t, uid in sorted(events, key=lambda e: (e[0], e[1])):
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        else:
            t = t.astimezone(timezone.utc)
        slot = floor_to_bucket(t, window_minutes)
        key = (uid, slot)
        if key in seen:
            continue
        seen.add(key)
        result.append(t)
    return result


def bucket_deduped_queue_join_counts(
    events: list[tuple[datetime, int]],
    range_start: datetime,
    range_end: datetime,
    bucket_minutes: int,
    dedupe_window_minutes: int,
) -> list[BucketRow]:
    """Bucket *events* after applying :func:`dedupe_per_fixed_window`."""

    kept_times = dedupe_per_fixed_window(events, dedupe_window_minutes)
    return bucket_queue_join_counts(kept_times, range_start, range_end, bucket_minutes)
