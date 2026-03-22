"""Invariant tests for the 1v1 matchmaker (backend.algorithms.matchmaker).

Tests check structural properties — conservation, uniqueness, window
compliance, population balance — not specific numerical outcomes.
"""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from backend.algorithms.matchmaker import (
    _build_candidates,
    _categorise,
    _equalise,
    run_matchmaking_wave,
)
from backend.core.config import (
    BALANCE_THRESHOLD_MMR,
    BASE_MMR_WINDOW,
    MMR_WINDOW_GROWTH_PER_CYCLE,
    WAIT_PRIORITY_COEFFICIENT,
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
        map_vetoes=[],
        joined_at=_NOW,
        wait_cycles=wait_cycles,
    )


# ---------------------------------------------------------------------------
# _categorise — Invariant 7: exhaustive disjoint partition
# ---------------------------------------------------------------------------


def test_categorise_partition() -> None:
    entries = [
        _entry(1, bw_race="bw_terran", bw_mmr=1500),
        _entry(2, sc2_race="sc2_zerg", sc2_mmr=1400),
        _entry(3, bw_race="bw_protoss", sc2_race="sc2_terran", bw_mmr=1600, sc2_mmr=1300),
        _entry(4, bw_race="bw_zerg", bw_mmr=1200),
    ]
    bw, sc2, both = _categorise(entries)
    all_uids = {e["discord_uid"] for e in bw + sc2 + both}
    input_uids = {e["discord_uid"] for e in entries}
    assert all_uids == input_uids
    assert len(bw) + len(sc2) + len(both) == len(entries)

    # Classification correctness.
    for e in bw:
        assert e["bw_race"] is not None and e["sc2_race"] is None
    for e in sc2:
        assert e["sc2_race"] is not None and e["bw_race"] is None
    for e in both:
        assert e["bw_race"] is not None and e["sc2_race"] is not None


# ---------------------------------------------------------------------------
# _categorise — Invariant 8: sort order
# ---------------------------------------------------------------------------


def test_categorise_sort_order() -> None:
    entries = [
        _entry(1, bw_race="bw_terran", bw_mmr=1200),
        _entry(2, bw_race="bw_zerg", bw_mmr=1800),
        _entry(3, bw_race="bw_protoss", bw_mmr=1500),
    ]
    bw, _, _ = _categorise(entries)
    mmrs = [e["bw_mmr"] for e in bw]
    assert mmrs == sorted(mmrs, reverse=True)


# ---------------------------------------------------------------------------
# _equalise — Invariant 9: conservation
# ---------------------------------------------------------------------------


def test_equalise_conservation() -> None:
    bw_in = [_entry(1, bw_race="bw_terran", bw_mmr=1500)]
    sc2_in = [_entry(2, sc2_race="sc2_zerg", sc2_mmr=1400)]
    both_in = [
        _entry(3, bw_race="bw_protoss", sc2_race="sc2_terran", bw_mmr=1600, sc2_mmr=1300),
        _entry(4, bw_race="bw_zerg", sc2_race="sc2_protoss", bw_mmr=1200, sc2_mmr=1700),
        _entry(5, bw_race="bw_terran", sc2_race="sc2_zerg", bw_mmr=1500, sc2_mmr=1500),
    ]
    bw_out, sc2_out = _equalise(bw_in, sc2_in, both_in)
    input_uids = {e["discord_uid"] for e in bw_in + sc2_in + both_in}
    output_uids = {e["discord_uid"] for e in bw_out + sc2_out}
    assert input_uids == output_uids
    assert len(bw_out) + len(sc2_out) == len(bw_in) + len(sc2_in) + len(both_in)


# ---------------------------------------------------------------------------
# _equalise — Invariant 10: population balance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n_bw,n_sc2,n_both",
    [(0, 0, 5), (0, 0, 6), (3, 0, 4), (0, 3, 4), (2, 2, 3), (1, 5, 2), (5, 1, 2)],
)
def test_equalise_population_balance(n_bw: int, n_sc2: int, n_both: int) -> None:
    uid = 1
    bw_in = []
    for _ in range(n_bw):
        bw_in.append(_entry(uid, bw_race="bw_terran", bw_mmr=1500))
        uid += 1
    sc2_in = []
    for _ in range(n_sc2):
        sc2_in.append(_entry(uid, sc2_race="sc2_zerg", sc2_mmr=1500))
        uid += 1
    both_in = []
    for _ in range(n_both):
        both_in.append(
            _entry(uid, bw_race="bw_terran", sc2_race="sc2_zerg", bw_mmr=1500, sc2_mmr=1500)
        )
        uid += 1

    bw_out, sc2_out = _equalise(bw_in, sc2_in, both_in)
    # The "both" pool can close the gap by at most len(both_in).
    # If the starting imbalance exceeds that, perfect balance isn't possible.
    starting_imbalance = abs(n_bw - n_sc2)
    best_possible = max(0, starting_imbalance - n_both)
    max_allowed = max(1, best_possible)
    assert abs(len(bw_out) - len(sc2_out)) <= max_allowed


# ---------------------------------------------------------------------------
# _equalise — Invariant 11: phase 3 doesn't worsen population balance
# ---------------------------------------------------------------------------


def test_equalise_phase3_no_worse_balance() -> None:
    """Soft rebalance should never make population balance worse."""
    bw_in = [_entry(i, bw_race="bw_terran", bw_mmr=1800) for i in range(1, 4)]
    sc2_in = [_entry(i, sc2_race="sc2_zerg", sc2_mmr=1200) for i in range(4, 7)]
    both_in = [
        _entry(7, bw_race="bw_protoss", sc2_race="sc2_terran", bw_mmr=1500, sc2_mmr=1500),
    ]
    bw_out, sc2_out = _equalise(bw_in, sc2_in, both_in)
    assert abs(len(bw_out) - len(sc2_out)) <= 1


# ---------------------------------------------------------------------------
# _equalise — Invariant 12: bias-aware split when both pools start empty
# ---------------------------------------------------------------------------


def test_equalise_empty_pools_bias_split() -> None:
    """When both dedicated pools are empty, the most BW-biased half should
    land in BW and the most SC2-biased in SC2."""
    both_in = [
        _entry(1, bw_race="bw_terran", sc2_race="sc2_zerg", bw_mmr=1800, sc2_mmr=1200),
        _entry(2, bw_race="bw_zerg", sc2_race="sc2_terran", bw_mmr=1200, sc2_mmr=1800),
    ]
    bw_out, sc2_out = _equalise([], [], both_in)
    bw_uids = {e["discord_uid"] for e in bw_out}
    sc2_uids = {e["discord_uid"] for e in sc2_out}
    # Player 1 is BW-biased (+600), player 2 is SC2-biased (-600).
    assert 1 in bw_uids
    assert 2 in sc2_uids


# ---------------------------------------------------------------------------
# _build_candidates — Invariant 13: no self-pairing
# ---------------------------------------------------------------------------


def test_build_candidates_no_self_pair() -> None:
    e = _entry(1, bw_race="bw_terran", sc2_race="sc2_zerg", bw_mmr=1500, sc2_mmr=1500)
    candidates = _build_candidates([e], [e], lead_is_bw=True)
    for _, le, fe, _ in candidates:
        assert le["discord_uid"] != fe["discord_uid"]


# ---------------------------------------------------------------------------
# _build_candidates — Invariant 14: window respected (disjunction)
# ---------------------------------------------------------------------------


def test_build_candidates_window_disjunction() -> None:
    lead = [_entry(1, bw_race="bw_terran", bw_mmr=1500, wait_cycles=0)]
    follow = [
        _entry(2, sc2_race="sc2_zerg", sc2_mmr=1500, wait_cycles=0),
        _entry(3, sc2_race="sc2_zerg", sc2_mmr=1700, wait_cycles=0),  # diff=200, window=100
        _entry(4, sc2_race="sc2_zerg", sc2_mmr=1700, wait_cycles=3),  # diff=200, window=250
    ]
    candidates = _build_candidates(lead, follow, lead_is_bw=True)
    for _, le, fe, diff in candidates:
        le_window = BASE_MMR_WINDOW + le["wait_cycles"] * MMR_WINDOW_GROWTH_PER_CYCLE
        fe_window = BASE_MMR_WINDOW + fe["wait_cycles"] * MMR_WINDOW_GROWTH_PER_CYCLE
        assert diff <= le_window or diff <= fe_window

    # Player 3 (diff=200, both windows=100) should be excluded.
    candidate_follow_uids = {fe["discord_uid"] for _, _, fe, _ in candidates}
    assert 3 not in candidate_follow_uids
    # Player 4 (diff=200, their window=250) should be included.
    assert 4 in candidate_follow_uids


# ---------------------------------------------------------------------------
# _build_candidates — Invariant 15: score formula
# ---------------------------------------------------------------------------


def test_build_candidates_score_formula() -> None:
    lead = [_entry(1, bw_race="bw_terran", bw_mmr=1500, wait_cycles=2)]
    follow = [_entry(2, sc2_race="sc2_zerg", sc2_mmr=1450, wait_cycles=3)]
    candidates = _build_candidates(lead, follow, lead_is_bw=True)
    assert len(candidates) == 1
    score, _, _, diff = candidates[0]
    expected_wait_factor = 3  # max(2, 3)
    expected_score = (diff**2) - ((2**expected_wait_factor) * WAIT_PRIORITY_COEFFICIENT)
    assert score == expected_score


# ---------------------------------------------------------------------------
# run_matchmaking_wave — Invariant 28: conservation
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
# run_matchmaking_wave — Invariant 29: no duplication
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
        matched_uids.add(m["player_1_discord_uid"])
        matched_uids.add(m["player_2_discord_uid"])
    # No overlap.
    assert remaining_uids & matched_uids == set()
    # No duplicate within matches.
    assert len(matched_uids) == len(matches) * 2


# ---------------------------------------------------------------------------
# run_matchmaking_wave — Invariant 30: wait_cycles incremented
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
# run_matchmaking_wave — Invariant 31: input not mutated
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
# run_matchmaking_wave — Invariant 32: degenerate inputs
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
    """Two BW-only players can't match (same era, both end up in BW pool)."""
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


# ---------------------------------------------------------------------------
# run_matchmaking_wave — Invariant 33: monotonic convergence
# ---------------------------------------------------------------------------


def test_wave_convergence_via_wait() -> None:
    """Two compatible players initially out of window must eventually match
    as wait_cycles grow the window."""
    mmr_gap = 400  # way beyond BASE_MMR_WINDOW=100
    queue = [
        _entry(1, bw_race="bw_terran", bw_mmr=1500),
        _entry(2, sc2_race="sc2_zerg", sc2_mmr=1500 + mmr_gap),
    ]
    # Calculate how many cycles needed: ceil((gap - BASE_MMR_WINDOW) / GROWTH)
    cycles_needed = (mmr_gap - BASE_MMR_WINDOW + MMR_WINDOW_GROWTH_PER_CYCLE - 1) // MMR_WINDOW_GROWTH_PER_CYCLE

    # Run waves until convergence.
    for _ in range(cycles_needed + 1):
        remaining, matches = run_matchmaking_wave(queue)
        if matches:
            break
        queue = remaining

    assert len(matches) == 1, f"Expected match after {cycles_needed + 1} cycles"
