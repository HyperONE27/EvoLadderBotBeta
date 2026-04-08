"""Invariant tests for the 1v1 matchmaker (backend.algorithms.matchmaker).

Tests check structural properties — conservation, uniqueness, window
compliance — not specific numerical outcomes.
"""

from copy import deepcopy
from datetime import datetime, timezone

from backend.algorithms.matchmaker import run_matchmaking_wave
from backend.core.config import (
    BASE_MMR_WINDOW,
    MMR_WINDOW_GROWTH_PER_CYCLE,
)
from backend.domain_types.ephemeral import QueueEntry1v1

_NOW = datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _entry(
    uid: int,
    *,
    bw_race: str | None = None,
    sc2_race: str | None = None,
    bw_mmr: int | None = None,
    sc2_mmr: int | None = None,
    wait_cycles: int = 0,
    location: str | None = None,
) -> QueueEntry1v1:
    return QueueEntry1v1(
        discord_uid=uid,
        player_name=f"player_{uid}",
        bw_race=bw_race,
        sc2_race=sc2_race,
        bw_mmr=bw_mmr,
        sc2_mmr=sc2_mmr,
        bw_letter_rank="U" if bw_race else None,
        sc2_letter_rank="U" if sc2_race else None,
        nationality=None,
        location=location,
        map_vetoes=[],
        joined_at=_NOW,
        wait_cycles=wait_cycles,
    )


# ---------------------------------------------------------------------------
# Conservation
# ---------------------------------------------------------------------------


def test_wave_conservation() -> None:
    queue = [
        _entry(1, bw_race="bw_terran", bw_mmr=1500),
        _entry(2, sc2_race="sc2_zerg", sc2_mmr=1500),
        _entry(3, bw_race="bw_protoss", bw_mmr=1400),
        _entry(4, sc2_race="sc2_terran", sc2_mmr=1400),
        _entry(5, bw_race="bw_zerg", sc2_race="sc2_protoss", bw_mmr=1600, sc2_mmr=1600),
    ]
    remaining, matches = run_matchmaking_wave(queue)
    matched_count = len(matches) * 2
    assert len(remaining) + matched_count == len(queue)


# ---------------------------------------------------------------------------
# No duplication / no self-match
# ---------------------------------------------------------------------------


def test_wave_no_duplication() -> None:
    queue = [
        _entry(i, bw_race="bw_terran", sc2_race="sc2_zerg", bw_mmr=1500, sc2_mmr=1500)
        for i in range(1, 9)
    ]
    remaining, matches = run_matchmaking_wave(queue)
    remaining_uids = {e["discord_uid"] for e in remaining}
    matched_uids: set[int] = set()
    for m in matches:
        # No self-match: a Both player must never play themselves.
        assert m["player_1_discord_uid"] != m["player_2_discord_uid"]
        matched_uids.add(m["player_1_discord_uid"])
        matched_uids.add(m["player_2_discord_uid"])
    # No overlap.
    assert remaining_uids & matched_uids == set()
    # No duplicate within matches.
    assert len(matched_uids) == len(matches) * 2


# ---------------------------------------------------------------------------
# MMR window respected
# ---------------------------------------------------------------------------


def test_wave_mmr_window_respected() -> None:
    """Every produced match must satisfy at least one player's MMR window."""
    queue = [
        _entry(1, bw_race="bw_terran", bw_mmr=1000, wait_cycles=0),
        _entry(2, sc2_race="sc2_zerg", sc2_mmr=1050, wait_cycles=0),  # diff=50, ok
        _entry(3, bw_race="bw_protoss", bw_mmr=2000, wait_cycles=0),
        _entry(4, sc2_race="sc2_terran", sc2_mmr=2050, wait_cycles=0),  # diff=50, ok
    ]
    _, matches = run_matchmaking_wave(queue)
    # 4 players, all within window of their adjacent rating → 2 matches.
    assert len(matches) == 2
    for m in matches:
        diff = abs(m["player_1_mmr"] - m["player_2_mmr"])
        assert diff <= BASE_MMR_WINDOW


def test_wave_excludes_out_of_window() -> None:
    """A pair beyond every window must not be matched."""
    queue = [
        _entry(1, bw_race="bw_terran", bw_mmr=1000),
        _entry(2, sc2_race="sc2_zerg", sc2_mmr=2000),  # diff=1000, both windows=100
    ]
    remaining, matches = run_matchmaking_wave(queue)
    assert matches == []
    assert len(remaining) == 2


# ---------------------------------------------------------------------------
# wait_cycles incremented for unmatched players
# ---------------------------------------------------------------------------


def test_wave_wait_cycles_incremented() -> None:
    queue = [
        _entry(1, bw_race="bw_terran", bw_mmr=1500, wait_cycles=3),
        _entry(2, bw_race="bw_zerg", bw_mmr=9999, wait_cycles=0),  # won't match
    ]
    remaining, _ = run_matchmaking_wave(queue)
    for e in remaining:
        original = next(q for q in queue if q["discord_uid"] == e["discord_uid"])
        assert e["wait_cycles"] == original["wait_cycles"] + 1


# ---------------------------------------------------------------------------
# Input not mutated
# ---------------------------------------------------------------------------


def test_wave_input_not_mutated() -> None:
    queue = [
        _entry(1, bw_race="bw_terran", bw_mmr=1500),
        _entry(2, sc2_race="sc2_zerg", sc2_mmr=1500),
    ]
    original = deepcopy(queue)
    run_matchmaking_wave(queue)
    assert queue == original


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------


def test_wave_empty_queue() -> None:
    remaining, matches = run_matchmaking_wave([])
    assert remaining == []
    assert matches == []


def test_wave_single_entry() -> None:
    queue = [_entry(1, bw_race="bw_terran", bw_mmr=1500)]
    remaining, matches = run_matchmaking_wave(queue)
    assert len(remaining) == 1
    assert matches == []
    assert remaining[0]["wait_cycles"] == 1


def test_wave_two_incompatible() -> None:
    """Two BW-only players can't match (no SC2 side)."""
    queue = [
        _entry(1, bw_race="bw_terran", bw_mmr=1500),
        _entry(2, bw_race="bw_zerg", bw_mmr=1500),
    ]
    remaining, matches = run_matchmaking_wave(queue)
    assert len(remaining) == 2
    assert matches == []


def test_wave_two_compatible() -> None:
    """One BW + one SC2 within window must match."""
    queue = [
        _entry(1, bw_race="bw_terran", bw_mmr=1500),
        _entry(2, sc2_race="sc2_zerg", sc2_mmr=1500),
    ]
    remaining, matches = run_matchmaking_wave(queue)
    assert len(remaining) == 0
    assert len(matches) == 1
    # The BW-only player must be the BW side; SC2-only the SC2 side.
    assert matches[0]["player_1_discord_uid"] == 1
    assert matches[0]["player_2_discord_uid"] == 2


# ---------------------------------------------------------------------------
# Both-player flexible side commitment (the whole point of the rewrite)
# ---------------------------------------------------------------------------


def test_both_player_picks_available_side() -> None:
    """A Both player facing only an SC2 opponent should commit to BW (and
    vice-versa). The Hungarian assignment is responsible for picking the
    side that yields a match instead of pre-committing the player."""
    # Queue: one Both player + one SC2-only opponent. The only way to
    # produce a match is for the Both player to play BW.
    queue = [
        _entry(
            1,
            bw_race="bw_terran",
            sc2_race="sc2_zerg",
            bw_mmr=1500,
            sc2_mmr=1500,
        ),
        _entry(2, sc2_race="sc2_protoss", sc2_mmr=1500),
    ]
    _, matches = run_matchmaking_wave(queue)
    assert len(matches) == 1
    # Both player committed to BW.
    assert matches[0]["player_1_discord_uid"] == 1
    assert matches[0]["player_1_race"] == "bw_terran"
    assert matches[0]["player_2_discord_uid"] == 2
    assert matches[0]["player_2_race"] == "sc2_protoss"

    # Mirror case: Both player must commit to SC2.
    queue2 = [
        _entry(
            1,
            bw_race="bw_terran",
            sc2_race="sc2_zerg",
            bw_mmr=1500,
            sc2_mmr=1500,
        ),
        _entry(2, bw_race="bw_protoss", bw_mmr=1500),
    ]
    _, matches2 = run_matchmaking_wave(queue2)
    assert len(matches2) == 1
    assert matches2[0]["player_1_discord_uid"] == 2
    assert matches2[0]["player_1_race"] == "bw_protoss"
    assert matches2[0]["player_2_discord_uid"] == 1
    assert matches2[0]["player_2_race"] == "sc2_zerg"


def test_both_player_not_self_matched() -> None:
    """A lone Both player must not be matched against themselves even
    though they appear on both axes of the cost matrix."""
    queue = [
        _entry(
            1,
            bw_race="bw_terran",
            sc2_race="sc2_zerg",
            bw_mmr=1500,
            sc2_mmr=1500,
        ),
    ]
    remaining, matches = run_matchmaking_wave(queue)
    assert matches == []
    assert len(remaining) == 1


# ---------------------------------------------------------------------------
# Disallowed region pairs (USB/FER vs CAM/SAM)
# ---------------------------------------------------------------------------


def test_wave_disallowed_region_pair_blocked() -> None:
    """USB vs CAM (and the other three USB/FER × CAM/SAM combos) must
    never produce a match, even if MMR and races are otherwise compatible."""
    queue = [
        _entry(1, bw_race="bw_terran", bw_mmr=1500, location="USB"),
        _entry(2, sc2_race="sc2_zerg", sc2_mmr=1500, location="CAM"),
    ]
    remaining, matches = run_matchmaking_wave(queue)
    assert matches == []
    assert len(remaining) == 2

    queue = [
        _entry(1, bw_race="bw_terran", bw_mmr=1500, location="FER"),
        _entry(2, sc2_race="sc2_zerg", sc2_mmr=1500, location="SAM"),
    ]
    _, matches = run_matchmaking_wave(queue)
    assert matches == []


def test_wave_disallowed_region_routes_to_alternative() -> None:
    """A USB player should still match a same-MMR EUE player even when a
    blocked CAM opponent is also in queue."""
    queue = [
        _entry(1, bw_race="bw_terran", bw_mmr=1500, location="USB"),
        _entry(2, sc2_race="sc2_zerg", sc2_mmr=1500, location="CAM"),
        _entry(3, sc2_race="sc2_protoss", sc2_mmr=1500, location="EUE"),
    ]
    _, matches = run_matchmaking_wave(queue)
    assert len(matches) == 1
    pair = {matches[0]["player_1_discord_uid"], matches[0]["player_2_discord_uid"]}
    assert pair == {1, 3}


def test_wave_unknown_location_not_blocked() -> None:
    """A player with no recorded location must not be filtered out."""
    queue = [
        _entry(1, bw_race="bw_terran", bw_mmr=1500, location=None),
        _entry(2, sc2_race="sc2_zerg", sc2_mmr=1500, location="CAM"),
    ]
    _, matches = run_matchmaking_wave(queue)
    assert len(matches) == 1


# ---------------------------------------------------------------------------
# Monotonic convergence: out-of-window pairs eventually match
# ---------------------------------------------------------------------------


def test_wave_convergence_via_wait() -> None:
    mmr_gap = 400  # way beyond BASE_MMR_WINDOW=100
    queue = [
        _entry(1, bw_race="bw_terran", bw_mmr=1500),
        _entry(2, sc2_race="sc2_zerg", sc2_mmr=1500 + mmr_gap),
    ]
    cycles_needed = (
        mmr_gap - BASE_MMR_WINDOW + MMR_WINDOW_GROWTH_PER_CYCLE - 1
    ) // MMR_WINDOW_GROWTH_PER_CYCLE

    matches: list = []
    for _ in range(cycles_needed + 1):
        remaining, matches = run_matchmaking_wave(queue)
        if matches:
            break
        queue = remaining

    assert len(matches) == 1, f"Expected match after {cycles_needed + 1} cycles"
