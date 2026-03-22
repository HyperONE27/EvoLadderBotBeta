"""Invariant tests for common.datetime_helpers.ensure_utc.

Key invariants:
- Naive datetime → UTC-aware (same wall clock)
- Already-UTC datetime → unchanged
- ISO string variants → UTC datetime
- None / garbage → None (no crash)
"""

from datetime import datetime, timezone, timedelta

from common.datetime_helpers import ensure_utc


class TestEnsureUtc:
    def test_naive_datetime_becomes_utc(self) -> None:
        naive = datetime(2026, 3, 17, 12, 0, 0)
        result = ensure_utc(naive)
        assert result is not None
        assert result.tzinfo == timezone.utc
        assert result.year == 2026 and result.month == 3 and result.hour == 12

    def test_utc_datetime_unchanged(self) -> None:
        aware = datetime(2026, 3, 17, 12, 0, 0, tzinfo=timezone.utc)
        result = ensure_utc(aware)
        assert result == aware

    def test_non_utc_aware_preserved(self) -> None:
        """An aware datetime with a non-UTC offset is returned as-is."""
        est = timezone(timedelta(hours=-5))
        aware = datetime(2026, 3, 17, 12, 0, 0, tzinfo=est)
        result = ensure_utc(aware)
        assert result is not None
        assert result.tzinfo == est
        assert result == aware

    def test_iso_string_z_suffix(self) -> None:
        result = ensure_utc("2026-03-17T12:00:00Z")
        assert result is not None
        assert result.tzinfo is not None
        assert result.hour == 12

    def test_iso_string_plus_zero(self) -> None:
        result = ensure_utc("2026-03-17T12:00:00+00:00")
        assert result is not None
        assert result.hour == 12

    def test_iso_string_short_offset(self) -> None:
        """'+00' without minutes is normalised."""
        result = ensure_utc("2026-03-17T12:00:00+00")
        assert result is not None
        assert result.hour == 12

    def test_none_returns_none(self) -> None:
        assert ensure_utc(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert ensure_utc("") is None

    def test_garbage_string_returns_none(self) -> None:
        assert ensure_utc("not-a-date") is None

    def test_non_string_non_datetime_returns_none(self) -> None:
        assert ensure_utc(12345) is None
        assert ensure_utc([]) is None
