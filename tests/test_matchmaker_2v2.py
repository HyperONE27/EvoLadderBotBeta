"""Invariant tests for the 2v2 matchmaker (backend.algorithms.matchmaker_2v2).

Tests check structural properties — compatibility truth table, cost matrix
symmetry, composition resolution, conservation — not specific outcomes.
"""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from backend.algorithms.matchmaker_2v2 import (
    _build_cost_matrix,
    _compatible,
    _resolve_to_candidate,
    run_matchmaking_wave_2v2,
)
from backend.core.config import (
    BASE_MMR_WINDOW,
    MMR_WINDOW_GROWTH_PER_CYCLE,
    WAIT_PRIORITY_COEFFICIENT,
)
from backend.domain_types.ephemeral import QueueEntry2v2

_NOW = datetime.now(tz=timezone.utc)
_SENTINEL: float = 1e18


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _team(
    uid: int,
    member_uid: int,
    *,
    pure_bw: tuple[str, str] | None = None,
    mixed: tuple[str, str] | None = None,
    pure_sc2: tuple[str, str] | None = None,
    mmr: int = 1500,
    wait_cycles: int = 0,
) -> QueueEntry2v2:
    return QueueEntry2v2(
        discord_uid=uid,
        player_name=f"leader_{uid}",
        party_member_discord_uid=member_uid,
        party_member_name=f"member_{member_uid}",
        pure_bw_leader_race=pure_bw[0] if pure_bw else None,
        pure_bw_member_race=pure_bw[1] if pure_bw else None,
        mixed_leader_race=mixed[0] if mixed else None,
        mixed_member_race=mixed[1] if mixed else None,
        pure_sc2_leader_race=pure_sc2[0] if pure_sc2 else None,
        pure_sc2_member_race=pure_sc2[1] if pure_sc2 else None,
        nationality="US",
        location=None,
        member_nationality="US",
        member_location=None,
        team_mmr=mmr,
        team_letter_rank="U",
        map_vetoes=[],
        joined_at=_NOW,
        wait_cycles=wait_cycles,
    )


# ---------------------------------------------------------------------------
# _compatible — Invariant 23: truth table and symmetry
# ---------------------------------------------------------------------------


class TestCompatible:
    def test_bw_vs_sc2(self) -> None:
        a = _team(1, 2, pure_bw=("bw_terran", "bw_zerg"))
        b = _team(3, 4, pure_sc2=("sc2_terran", "sc2_zerg"))
        assert _compatible(a, b) is True
        assert _compatible(b, a) is True  # symmetry

    def test_bw_sc2_vs_bw_sc2(self) -> None:
        a = _team(1, 2, mixed=("bw_terran", "sc2_zerg"))
        b = _team(3, 4, mixed=("sc2_protoss", "bw_protoss"))
        assert _compatible(a, b) is True

    def test_same_era_incompatible(self) -> None:
        a = _team(1, 2, pure_bw=("bw_terran", "bw_zerg"))
        b = _team(3, 4, pure_bw=("bw_protoss", "bw_terran"))
        assert _compatible(a, b) is False

    def test_sc2_vs_sc2_incompatible(self) -> None:
        a = _team(1, 2, pure_sc2=("sc2_terran", "sc2_zerg"))
        b = _team(3, 4, pure_sc2=("sc2_protoss", "sc2_terran"))
        assert _compatible(a, b) is False

    def test_multi_comp_compatible(self) -> None:
        """Team with both BW and SC2 declared is compatible with either."""
        a = _team(
            1, 2, pure_bw=("bw_terran", "bw_zerg"), pure_sc2=("sc2_terran", "sc2_zerg")
        )
        b = _team(3, 4, pure_bw=("bw_protoss", "bw_terran"))
        assert (
            _compatible(a, b) is True
        )  # a.has_sc2 and b.has_bw? No. a.has_bw and b... wait
        # a has both bw and sc2.  b has bw only.
        # _compatible: a.has_sc2(yes) and b.has_bw(yes) → True
        assert _compatible(b, a) is True

    def test_symmetry(self) -> None:
        """_compatible(a, b) == _compatible(b, a) for all comp combinations."""
        comps = [
            {"pure_bw": ("bw_terran", "bw_zerg")},
            {"pure_sc2": ("sc2_terran", "sc2_zerg")},
            {"mixed": ("bw_terran", "sc2_zerg")},
            {
                "pure_bw": ("bw_terran", "bw_zerg"),
                "pure_sc2": ("sc2_terran", "sc2_zerg"),
            },
            {
                "pure_bw": ("bw_terran", "bw_zerg"),
                "mixed": ("bw_protoss", "sc2_terran"),
            },
        ]
        uid = 1
        for i, comp_a in enumerate(comps):
            a = _team(uid, uid + 1, **comp_a)
            uid += 2
            for j, comp_b in enumerate(comps):
                b = _team(uid, uid + 1, **comp_b)
                uid += 2
                assert _compatible(a, b) == _compatible(b, a), (
                    f"Symmetry violated for comp[{i}] vs comp[{j}]"
                )


# ---------------------------------------------------------------------------
# _build_cost_matrix — Invariants 16-19
# ---------------------------------------------------------------------------


class TestCostMatrix:
    def test_diagonal_sentinel(self) -> None:
        """Invariant 16: diagonal is always sentinel."""
        teams = [
            _team(1, 2, pure_bw=("bw_terran", "bw_zerg")),
            _team(3, 4, pure_sc2=("sc2_terran", "sc2_zerg")),
            _team(5, 6, mixed=("bw_terran", "sc2_zerg")),
        ]
        cost = _build_cost_matrix(teams)
        for i in range(len(teams)):
            assert cost[i][i] == _SENTINEL

    def test_symmetry(self) -> None:
        """Invariant 17: cost[i][j] == cost[j][i]."""
        teams = [
            _team(1, 2, pure_bw=("bw_terran", "bw_zerg"), mmr=1500),
            _team(3, 4, pure_sc2=("sc2_terran", "sc2_zerg"), mmr=1400),
            _team(5, 6, mixed=("bw_terran", "sc2_zerg"), mmr=1600),
            _team(7, 8, mixed=("sc2_protoss", "bw_protoss"), mmr=1450),
        ]
        cost = _build_cost_matrix(teams)
        n = len(teams)
        for i in range(n):
            for j in range(n):
                assert cost[i][j] == cost[j][i], f"Asymmetry at ({i},{j})"

    def test_sentinel_biconditional(self) -> None:
        """Invariant 18: non-sentinel ↔ compatible AND within window."""
        teams = [
            _team(1, 2, pure_bw=("bw_terran", "bw_zerg"), mmr=1500, wait_cycles=0),
            _team(3, 4, pure_sc2=("sc2_terran", "sc2_zerg"), mmr=1500, wait_cycles=0),
            _team(5, 6, pure_bw=("bw_protoss", "bw_terran"), mmr=1500, wait_cycles=0),
            # Out of window: mmr diff=400, window=100 for wait_cycles=0
            _team(7, 8, pure_sc2=("sc2_zerg", "sc2_protoss"), mmr=1900, wait_cycles=0),
        ]
        cost = _build_cost_matrix(teams)
        n = len(teams)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = teams[i], teams[j]
                compat = _compatible(a, b)
                diff = abs(a["team_mmr"] - b["team_mmr"])
                a_window = (
                    BASE_MMR_WINDOW + a["wait_cycles"] * MMR_WINDOW_GROWTH_PER_CYCLE
                )
                b_window = (
                    BASE_MMR_WINDOW + b["wait_cycles"] * MMR_WINDOW_GROWTH_PER_CYCLE
                )
                in_window = diff <= a_window or diff <= b_window
                should_be_valid = compat and in_window
                is_valid = cost[i][j] < _SENTINEL
                assert is_valid == should_be_valid, (
                    f"({i},{j}): compat={compat}, in_window={in_window}, "
                    f"cost={cost[i][j]}"
                )

    def test_score_formula(self) -> None:
        """Invariant 19: non-sentinel cells match the expected formula."""
        teams = [
            _team(1, 2, pure_bw=("bw_terran", "bw_zerg"), mmr=1500, wait_cycles=2),
            _team(3, 4, pure_sc2=("sc2_terran", "sc2_zerg"), mmr=1450, wait_cycles=3),
        ]
        cost = _build_cost_matrix(teams)
        diff = abs(1500 - 1450)
        wait_factor = max(2, 3)
        expected = (diff**2) - ((2**wait_factor) * WAIT_PRIORITY_COEFFICIENT)
        assert cost[0][1] == expected
        assert cost[1][0] == expected


# ---------------------------------------------------------------------------
# _resolve_to_candidate — Invariants 24-27
# ---------------------------------------------------------------------------


class TestResolveToCandidate:
    def test_all_race_fields_populated(self) -> None:
        """Invariant 24: all 8 race fields are non-None."""
        a = _team(1, 2, pure_bw=("bw_terran", "bw_zerg"))
        b = _team(3, 4, pure_sc2=("sc2_terran", "sc2_zerg"))
        candidate = _resolve_to_candidate(a, b)
        assert candidate["team_1_player_1_race"] is not None
        assert candidate["team_1_player_2_race"] is not None
        assert candidate["team_2_player_1_race"] is not None
        assert candidate["team_2_player_2_race"] is not None

    def test_bw_team_is_team_1(self) -> None:
        """Invariant 25: in cross-era, BW team is always team_1."""
        a = _team(1, 2, pure_bw=("bw_terran", "bw_zerg"))
        b = _team(3, 4, pure_sc2=("sc2_terran", "sc2_zerg"))
        candidate = _resolve_to_candidate(a, b)
        assert candidate["team_1_player_1_race"].startswith("bw_")
        assert candidate["team_1_player_2_race"].startswith("bw_")
        assert candidate["team_2_player_1_race"].startswith("sc2_")
        assert candidate["team_2_player_2_race"].startswith("sc2_")

    def test_bw_team_is_team_1_reversed(self) -> None:
        """Same invariant when the SC2 team is passed first."""
        a = _team(1, 2, pure_sc2=("sc2_terran", "sc2_zerg"))
        b = _team(3, 4, pure_bw=("bw_terran", "bw_zerg"))
        candidate = _resolve_to_candidate(a, b)
        assert candidate["team_1_player_1_race"].startswith("bw_")
        assert candidate["team_1_player_2_race"].startswith("bw_")
        assert candidate["team_2_player_1_race"].startswith("sc2_")
        assert candidate["team_2_player_2_race"].startswith("sc2_")

    def test_leader_member_mapping(self) -> None:
        """Invariant 26: player_1 is always the leader, player_2 the member."""
        a = _team(1, 2, pure_bw=("bw_terran", "bw_zerg"))
        b = _team(3, 4, pure_sc2=("sc2_terran", "sc2_zerg"))
        candidate = _resolve_to_candidate(a, b)
        # BW team (a) is team_1.
        assert candidate["team_1_player_1_discord_uid"] == 1  # leader
        assert candidate["team_1_player_2_discord_uid"] == 2  # member
        # SC2 team (b) is team_2.
        assert candidate["team_2_player_1_discord_uid"] == 3  # leader
        assert candidate["team_2_player_2_discord_uid"] == 4  # member

    def test_bw_sc2_preserves_declared_races(self) -> None:
        """BW + SC2 comp: races pass through unchanged."""
        a = _team(1, 2, mixed=("bw_terran", "sc2_zerg"))
        b = _team(3, 4, mixed=("sc2_protoss", "bw_protoss"))
        candidate = _resolve_to_candidate(a, b)
        # team_1 is a (caller order preserved for BW + SC2).
        assert candidate["team_1_player_1_race"] == "bw_terran"
        assert candidate["team_1_player_2_race"] == "sc2_zerg"
        assert candidate["team_2_player_1_race"] == "sc2_protoss"
        assert candidate["team_2_player_2_race"] == "bw_protoss"

    def test_valueerror_on_inconsistent_comp(self) -> None:
        """Invariant 27: ValueError if a declared comp has None race slots."""
        # Manually construct a broken entry: has_bw is True (leader set) but member is None.
        a = _team(1, 2, pure_bw=("bw_terran", "bw_zerg"))
        b = _team(3, 4, pure_sc2=("sc2_terran", "sc2_zerg"))
        # Corrupt a's member race.
        a["pure_bw_member_race"] = None  # type: ignore[typeddict-item]
        with pytest.raises(ValueError, match="None races"):
            _resolve_to_candidate(a, b)


# ---------------------------------------------------------------------------
# run_matchmaking_wave_2v2 — Invariants 28-33
# ---------------------------------------------------------------------------


class TestWave2v2:
    def test_conservation(self) -> None:
        """Invariant 28: remaining + matched*2 == input."""
        queue = [
            _team(1, 2, pure_bw=("bw_terran", "bw_zerg"), mmr=1500),
            _team(3, 4, pure_sc2=("sc2_terran", "sc2_zerg"), mmr=1500),
            _team(5, 6, mixed=("bw_terran", "sc2_zerg"), mmr=1400),
            _team(7, 8, mixed=("sc2_protoss", "bw_protoss"), mmr=1400),
            _team(9, 10, pure_bw=("bw_protoss", "bw_terran"), mmr=1600),
        ]
        remaining, matches = run_matchmaking_wave_2v2(queue)
        assert len(remaining) + len(matches) * 2 == len(queue)

    def test_no_duplication(self) -> None:
        """Invariant 29: every team UID appears at most once across outputs."""
        queue = [
            _team(1, 2, pure_bw=("bw_terran", "bw_zerg"), mmr=1500),
            _team(3, 4, pure_sc2=("sc2_terran", "sc2_zerg"), mmr=1500),
            _team(5, 6, pure_bw=("bw_protoss", "bw_terran"), mmr=1500),
            _team(7, 8, pure_sc2=("sc2_zerg", "sc2_protoss"), mmr=1500),
        ]
        remaining, matches = run_matchmaking_wave_2v2(queue)
        remaining_uids = {e["discord_uid"] for e in remaining}
        matched_uids: set[int] = set()
        for m in matches:
            matched_uids.add(m["team_1_player_1_discord_uid"])
            matched_uids.add(m["team_2_player_1_discord_uid"])
        # Leader UIDs are used as the queue entry key.
        assert remaining_uids & matched_uids == set()
        assert len(matched_uids) == len(matches) * 2

    def test_wait_cycles_incremented(self) -> None:
        """Invariant 30: all remaining entries have wait_cycles + 1."""
        queue = [
            _team(1, 2, pure_bw=("bw_terran", "bw_zerg"), mmr=1500, wait_cycles=5),
        ]
        remaining, _ = run_matchmaking_wave_2v2(queue)
        assert remaining[0]["wait_cycles"] == 6

    def test_input_not_mutated(self) -> None:
        """Invariant 31: original queue is untouched."""
        queue = [
            _team(1, 2, pure_bw=("bw_terran", "bw_zerg"), mmr=1500),
            _team(3, 4, pure_sc2=("sc2_terran", "sc2_zerg"), mmr=1500),
        ]
        original = deepcopy(queue)
        run_matchmaking_wave_2v2(queue)
        assert queue == original

    def test_empty_queue(self) -> None:
        """Invariant 32: empty input."""
        remaining, matches = run_matchmaking_wave_2v2([])
        assert remaining == []
        assert matches == []

    def test_single_entry(self) -> None:
        """Invariant 32: single entry."""
        queue = [_team(1, 2, pure_bw=("bw_terran", "bw_zerg"))]
        remaining, matches = run_matchmaking_wave_2v2(queue)
        assert len(remaining) == 1
        assert matches == []
        assert remaining[0]["wait_cycles"] == 1

    def test_two_incompatible(self) -> None:
        """Invariant 32: two same-era teams can't match."""
        queue = [
            _team(1, 2, pure_bw=("bw_terran", "bw_zerg"), mmr=1500),
            _team(3, 4, pure_bw=("bw_protoss", "bw_terran"), mmr=1500),
        ]
        remaining, matches = run_matchmaking_wave_2v2(queue)
        assert len(remaining) == 2
        assert matches == []

    def test_two_compatible(self) -> None:
        """Invariant 32: BW + SC2 within window must match."""
        queue = [
            _team(1, 2, pure_bw=("bw_terran", "bw_zerg"), mmr=1500),
            _team(3, 4, pure_sc2=("sc2_terran", "sc2_zerg"), mmr=1500),
        ]
        remaining, matches = run_matchmaking_wave_2v2(queue)
        assert len(remaining) == 0
        assert len(matches) == 1

    def test_convergence_via_wait(self) -> None:
        """Invariant 33: out-of-window teams eventually match."""
        mmr_gap = 400
        queue: list[QueueEntry2v2] = [
            _team(1, 2, pure_bw=("bw_terran", "bw_zerg"), mmr=1500),
            _team(3, 4, pure_sc2=("sc2_terran", "sc2_zerg"), mmr=1500 + mmr_gap),
        ]
        cycles_needed = (
            mmr_gap - BASE_MMR_WINDOW + MMR_WINDOW_GROWTH_PER_CYCLE - 1
        ) // MMR_WINDOW_GROWTH_PER_CYCLE
        for _ in range(cycles_needed + 1):
            remaining, matches = run_matchmaking_wave_2v2(queue)
            if matches:
                break
            queue = remaining

        assert len(matches) == 1, f"Expected match after {cycles_needed + 1} cycles"
