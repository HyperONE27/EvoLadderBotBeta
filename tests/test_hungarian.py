"""Invariant tests for the Hungarian (Kuhn-Munkres) algorithm.

The 1v1 and 2v2 matchmakers each have their own copy.  Both are tested —
if one copy drifts or breaks independently, we catch it.

Key invariants:
- The output is a valid permutation (bijection from rows to columns).
- The total assignment cost is minimal among all possible permutations.
- Sentinel-only matrices produce all-sentinel assignments.
"""

import itertools
from typing import Callable

import pytest

from backend.algorithms.matchmaker import _hungarian_minimize as _hungarian_1v1
from backend.algorithms.matchmaker_2v2 import _hungarian_minimize as _hungarian_2v2

_SENTINEL: float = 1e18

HungarianFn = Callable[[list[list[float]], int], list[int]]


@pytest.fixture(params=[_hungarian_1v1, _hungarian_2v2], ids=["1v1", "2v2"])
def hungarian(request: pytest.FixtureRequest) -> HungarianFn:
    return request.param  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _brute_force_min_cost(cost: list[list[float]], n: int) -> float:
    """Exhaustively find the minimum total cost over all n! permutations."""
    best = float("inf")
    for perm in itertools.permutations(range(n)):
        total = sum(cost[i][perm[i]] for i in range(n))
        if total < best:
            best = total
    return best


def _assignment_cost(cost: list[list[float]], assignment: list[int]) -> float:
    return sum(cost[i][assignment[i]] for i in range(len(assignment)))


# ---------------------------------------------------------------------------
# Invariant 20 — Valid permutation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
def test_output_is_permutation(hungarian: HungarianFn, n: int) -> None:
    """Every row maps to a unique column, covering all columns."""
    cost = [[float(abs(i - j)) for j in range(n)] for i in range(n)]
    result = hungarian(cost, n)
    assert sorted(result) == list(range(n))


# ---------------------------------------------------------------------------
# Invariant 21 — Optimality (brute-force verified for small n)
# ---------------------------------------------------------------------------


def test_optimality_identity(hungarian: HungarianFn) -> None:
    """Diagonal-zero matrix: optimal is the identity assignment (cost 0)."""
    n = 4
    cost = [[0.0 if i == j else 10.0 for j in range(n)] for i in range(n)]
    result = hungarian(cost, n)
    assert _assignment_cost(cost, result) == 0.0


def test_optimality_reverse(hungarian: HungarianFn) -> None:
    """Anti-diagonal matrix: optimal is the reverse assignment."""
    n = 4
    cost = [[0.0 if i + j == n - 1 else 10.0 for j in range(n)] for i in range(n)]
    result = hungarian(cost, n)
    assert _assignment_cost(cost, result) == 0.0


def test_optimality_asymmetric(hungarian: HungarianFn) -> None:
    """Hand-crafted asymmetric matrix verified against brute force."""
    cost = [
        [10.0, 5.0, 13.0],
        [3.0, 7.0, 15.0],
        [8.0, 12.0, 4.0],
    ]
    n = 3
    result = hungarian(cost, n)
    actual = _assignment_cost(cost, result)
    expected = _brute_force_min_cost(cost, n)
    assert actual == expected


@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_optimality_brute_force_random_like(hungarian: HungarianFn, n: int) -> None:
    """Deterministic pseudo-random matrices verified against brute force.

    Uses a simple formula to generate varied but reproducible costs.
    """
    cost = [
        [float(((i * 7 + j * 13 + i * j * 3) % 47) + 1) for j in range(n)]
        for i in range(n)
    ]
    result = hungarian(cost, n)
    actual = _assignment_cost(cost, result)
    expected = _brute_force_min_cost(cost, n)
    assert actual == expected


# ---------------------------------------------------------------------------
# Invariant 22 — Sentinel avoidance
# ---------------------------------------------------------------------------


def test_sentinel_only_matrix(hungarian: HungarianFn) -> None:
    """When all cells are sentinel, the assignment still covers all rows
    but every pair lands on a sentinel cell."""
    n = 3
    cost = [[_SENTINEL] * n for _ in range(n)]
    result = hungarian(cost, n)
    assert sorted(result) == list(range(n))
    for i, j in enumerate(result):
        assert cost[i][j] == _SENTINEL


def test_prefers_non_sentinel(hungarian: HungarianFn) -> None:
    """When one non-sentinel path exists in a mostly-sentinel matrix,
    the algorithm finds it."""
    n = 3
    cost = [[_SENTINEL] * n for _ in range(n)]
    cost[0][1] = 1.0
    cost[1][2] = 2.0
    cost[2][0] = 3.0
    result = hungarian(cost, n)
    actual = _assignment_cost(cost, result)
    expected = _brute_force_min_cost(cost, n)
    assert actual == expected
    assert actual == 6.0


def test_mixed_sentinel_and_valid(hungarian: HungarianFn) -> None:
    """Sparse matrix with some sentinel and some valid cells."""
    n = 4
    cost = [[_SENTINEL] * n for _ in range(n)]
    cost[0][0] = 5.0
    cost[1][1] = 3.0
    cost[2][2] = 7.0
    cost[3][3] = 1.0
    cost[0][1] = 2.0
    cost[1][0] = 4.0
    cost[2][3] = 6.0
    cost[3][2] = 8.0
    result = hungarian(cost, n)
    actual = _assignment_cost(cost, result)
    expected = _brute_force_min_cost(cost, n)
    assert actual == expected


# ---------------------------------------------------------------------------
# Edge case — n=1
# ---------------------------------------------------------------------------


def test_single_element(hungarian: HungarianFn) -> None:
    """1x1 matrix: trivially assigned."""
    cost = [[42.0]]
    result = hungarian(cost, 1)
    assert result == [0]


# ---------------------------------------------------------------------------
# Negative costs (wait bonus can make scores negative)
# ---------------------------------------------------------------------------


def test_negative_costs(hungarian: HungarianFn) -> None:
    """The algorithm handles negative costs correctly (common when wait
    bonus dominates MMR difference)."""
    cost = [
        [-100.0, 50.0, _SENTINEL],
        [50.0, -200.0, 30.0],
        [_SENTINEL, 30.0, -50.0],
    ]
    n = 3
    result = hungarian(cost, n)
    actual = _assignment_cost(cost, result)
    expected = _brute_force_min_cost(cost, n)
    assert actual == expected
