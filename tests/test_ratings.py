"""Invariant tests for the ELO rating system (backend.algorithms.ratings_1v1).

Every test here is a property check — it must hold regardless of K-factor,
divisor, or default MMR values.  No test encodes a specific numerical outcome.
"""

import pytest

from backend.algorithms.ratings_1v1 import (
    get_new_ratings,
    get_potential_rating_changes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A spread of MMR pairs covering equal, close, and lopsided matchups.
MMR_PAIRS: list[tuple[int, int]] = [
    (1500, 1500),
    (1500, 1400),
    (1500, 1600),
    (1200, 1800),
    (1800, 1200),
    (1000, 2000),
    (1500, 1501),
    (100, 100),
    (3000, 3000),
]


# ---------------------------------------------------------------------------
# Invariant 1 — Zero-sum (conservation of total MMR)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("p1,p2", MMR_PAIRS)
@pytest.mark.parametrize("result", [0, 1, 2])
def test_zero_sum(p1: int, p2: int, result: int) -> None:
    """Total MMR before and after must differ by at most 1 (rounding)."""
    new_p1, new_p2 = get_new_ratings(p1, p2, result)
    assert abs((new_p1 + new_p2) - (p1 + p2)) <= 1


# ---------------------------------------------------------------------------
# Invariant 2 — Directional correctness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("p1,p2", MMR_PAIRS)
def test_winner_gains_loser_loses(p1: int, p2: int) -> None:
    """The winner's MMR goes up (or stays), the loser's goes down (or stays)."""
    # p1 wins
    new_p1, new_p2 = get_new_ratings(p1, p2, 1)
    assert new_p1 >= p1
    assert new_p2 <= p2

    # p2 wins
    new_p1, new_p2 = get_new_ratings(p1, p2, 2)
    assert new_p1 <= p1
    assert new_p2 >= p2


@pytest.mark.parametrize("p1,p2", MMR_PAIRS)
def test_draw_pulls_toward_centre(p1: int, p2: int) -> None:
    """On draw, the higher-rated player's MMR goes down (or stays flat) and
    the lower-rated player's goes up (or stays flat)."""
    new_p1, new_p2 = get_new_ratings(p1, p2, 0)
    if p1 > p2:
        assert new_p1 <= p1
        assert new_p2 >= p2
    elif p1 < p2:
        assert new_p1 >= p1
        assert new_p2 <= p2
    else:
        # Equal MMR draw → no change.
        assert new_p1 == p1
        assert new_p2 == p2


# ---------------------------------------------------------------------------
# Invariant 3 — Symmetry of perspective
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("p1,p2", MMR_PAIRS)
def test_slot_symmetry(p1: int, p2: int) -> None:
    """The p1 slot is not privileged.  A player with MMR X beating an
    opponent with MMR Y gets the same gain regardless of which slot
    they occupy."""
    # A (MMR=p1) wins as p1 vs B (MMR=p2).
    a_gain_as_p1 = get_new_ratings(p1, p2, 1)[0] - p1
    # A (MMR=p1) wins as p2 vs B (MMR=p2).  result=2 means p2 wins.
    a_gain_as_p2 = get_new_ratings(p2, p1, 2)[1] - p1
    assert a_gain_as_p1 == a_gain_as_p2


# ---------------------------------------------------------------------------
# Invariant 4 — Upset bonus
# ---------------------------------------------------------------------------


def test_underdog_gains_more() -> None:
    """When the underdog wins, their gain is strictly larger than the
    favourite's gain would be for winning the same matchup."""
    lo, hi = 1200, 1800
    # Underdog (lo) wins as p1
    underdog_gain = get_new_ratings(lo, hi, 1)[0] - lo
    # Favourite (hi) wins as p1
    favourite_gain = get_new_ratings(hi, lo, 1)[0] - hi
    assert underdog_gain > favourite_gain > 0


# ---------------------------------------------------------------------------
# Invariant 5 — Input validation
# ---------------------------------------------------------------------------


def test_invalid_result_raises() -> None:
    with pytest.raises(ValueError):
        get_new_ratings(1500, 1500, 3)
    with pytest.raises(ValueError):
        get_new_ratings(1500, 1500, -1)


def test_non_int_mmr_raises() -> None:
    with pytest.raises(ValueError):
        get_new_ratings(1500.0, 1500, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        get_new_ratings(1500, "1500", 1)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Invariant 6 — Potential changes consistent with actual changes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("p1,p2", MMR_PAIRS)
def test_potential_matches_actual(p1: int, p2: int) -> None:
    """get_potential_rating_changes must agree with get_new_ratings."""
    win_change, loss_change, draw_change = get_potential_rating_changes(p1, p2)

    actual_win = get_new_ratings(p1, p2, 1)[0] - p1
    actual_loss = get_new_ratings(p1, p2, 2)[0] - p1
    actual_draw = get_new_ratings(p1, p2, 0)[0] - p1

    assert win_change == actual_win
    assert loss_change == actual_loss
    assert draw_change == actual_draw
