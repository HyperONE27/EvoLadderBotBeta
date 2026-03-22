"""Invariant tests for replay verification helpers.

Covers _is_ai_player, _verify_mod, and _verify_timestamp — the three
stateless internal helpers that carry the most branching logic.
"""

from datetime import datetime, timezone, timedelta

from backend.algorithms.replay_verifier import (
    _is_ai_player,
    _verify_mod,
    _verify_timestamp,
)


# ---------------------------------------------------------------------------
# _is_ai_player
# ---------------------------------------------------------------------------


class TestIsAiPlayer:
    def test_ai_with_parentheses(self) -> None:
        assert _is_ai_player("A.I. 3 (Insane)") is True

    def test_ai_with_digits(self) -> None:
        assert _is_ai_player("Computer 1") is True
        assert _is_ai_player("AI9") is True

    def test_ai_with_period(self) -> None:
        assert _is_ai_player("A.I.") is True

    def test_clean_name(self) -> None:
        assert _is_ai_player("PlayerName") is False
        assert _is_ai_player("xXDarkLordXx") is False

    def test_zero_not_detected(self) -> None:
        """'0' is not in the detection set (only 1-9)."""
        assert _is_ai_player("Player0") is False

    def test_empty_string(self) -> None:
        assert _is_ai_player("") is False


# ---------------------------------------------------------------------------
# _verify_mod
# ---------------------------------------------------------------------------


MODS_WITH_HANDLES: dict = {
    "multi": {
        "am_handles": ["handle_am_1", "handle_am_2"],
        "eu_handles": ["handle_eu_1"],
        "as_handles": ["handle_as_1"],
        "am_artmod_handles": ["artmod_am_1"],
        "eu_artmod_handles": ["artmod_eu_1"],
        "as_artmod_handles": [],
    }
}


class TestVerifyMod:
    def test_matching_handle_passes(self) -> None:
        result = _verify_mod(["handle_am_1", "some_other_handle"], MODS_WITH_HANDLES)
        assert result["success"] is True

    def test_artmod_handle_passes(self) -> None:
        result = _verify_mod(["artmod_eu_1"], MODS_WITH_HANDLES)
        assert result["success"] is True

    def test_no_matching_handle_fails(self) -> None:
        result = _verify_mod(["unknown_handle"], MODS_WITH_HANDLES)
        assert result["success"] is False

    def test_empty_handles_fails(self) -> None:
        result = _verify_mod([], MODS_WITH_HANDLES)
        assert result["success"] is False

    def test_missing_multi_key_fails(self) -> None:
        result = _verify_mod(["handle_am_1"], {})
        assert result["success"] is False

    def test_none_multi_fails(self) -> None:
        result = _verify_mod(["handle_am_1"], {"multi": None})
        assert result["success"] is False


# ---------------------------------------------------------------------------
# _verify_timestamp
# ---------------------------------------------------------------------------


class TestVerifyTimestamp:
    def _assigned_at(self) -> datetime:
        return datetime(2026, 3, 17, 12, 0, 0, tzinfo=timezone.utc)

    def test_within_window_passes(self) -> None:
        replay_time = self._assigned_at() + timedelta(minutes=10)
        result = _verify_timestamp(replay_time.isoformat(), self._assigned_at().isoformat())
        assert result["success"] is True

    def test_at_zero_passes(self) -> None:
        """Replay exactly at assignment time is valid."""
        result = _verify_timestamp(
            self._assigned_at().isoformat(), self._assigned_at().isoformat()
        )
        assert result["success"] is True

    def test_before_assignment_fails(self) -> None:
        replay_time = self._assigned_at() - timedelta(minutes=5)
        result = _verify_timestamp(replay_time.isoformat(), self._assigned_at().isoformat())
        assert result["success"] is False

    def test_after_window_fails(self) -> None:
        # REPLAY_TIMESTAMP_WINDOW_MINUTES is 60.
        replay_time = self._assigned_at() + timedelta(minutes=61)
        result = _verify_timestamp(replay_time.isoformat(), self._assigned_at().isoformat())
        assert result["success"] is False

    def test_no_replay_time_fails(self) -> None:
        result = _verify_timestamp("", self._assigned_at().isoformat())
        assert result["success"] is False

    def test_no_assigned_at_fails(self) -> None:
        replay_time = self._assigned_at() + timedelta(minutes=5)
        result = _verify_timestamp(replay_time.isoformat(), None)
        assert result["success"] is False
