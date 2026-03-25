"""
Stateless 2v2 matchmaking service.

Single entry point: ``run_matchmaking_wave_2v2``

Accepts a list of ``QueueEntry2v2`` objects (one per party, created by the
party leader) and returns:
  - a list of ``QueueEntry2v2`` objects for teams still waiting, with
    ``wait_cycles`` incremented by 1 for every unmatched team, and
  - a list of ``MatchCandidate2v2`` objects for newly formed matches.

No global state, no singletons, no I/O, no mutation of the input list.

Algorithm
---------
Inspired by Dota 2 / LoL role-queue: find the match first, resolve
composition afterward.

Step 1 — Build an n×n cost matrix over all teams:
    cost[i][j] = mmr_diff² − 2^wait_factor × WAIT_PRIORITY_COEFFICIENT
                 if teams i and j are compatible and within each other's
                 MMR window; _SENTINEL otherwise.
    cost[i][i] = _SENTINEL (no self-match).
    The matrix is symmetric (cost[i][j] == cost[j][i]).

Two teams are compatible if any of the following hold:
    A.has_bw  and B.has_sc2   →  BW+BW vs SC2+SC2 is possible
    A.has_sc2 and B.has_bw   →  BW+BW vs SC2+SC2 is possible (roles swap)
    A.has_mixed and B.has_mixed →  BW + SC2 vs BW + SC2 is possible

Step 2 — Run the O(n³) Hungarian algorithm on the cost matrix to find a
minimum-weight maximum-cardinality matching.  Incompatible and out-of-window
pairs carry _SENTINEL cost so they are never selected unless no valid pair
exists.

Step 3 — Extract unique matched pairs from the assignment (deduplicating
the symmetric result) and resolve each pair's composition directly:
    - BW+BW vs SC2+SC2: the BW team is always team_1, SC2 team is team_2.
      If both teams could play either role, the assignment is randomised.
    - BW + SC2 vs BW + SC2: both teams use their declared BW + SC2 comp.
    When a pair is valid under both compositions, one is chosen randomly.
"""

from __future__ import annotations

import random
from copy import deepcopy

from backend.core.config import (
    BASE_MMR_WINDOW,
    MMR_WINDOW_GROWTH_PER_CYCLE,
    WAIT_PRIORITY_COEFFICIENT,
)
from backend.domain_types.ephemeral import MatchCandidate2v2, QueueEntry2v2

# Sentinel cost for incompatible / out-of-window / diagonal cells.
_SENTINEL: float = 1e18


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _max_mmr_diff(wait_cycles: int) -> int:
    return BASE_MMR_WINDOW + wait_cycles * MMR_WINDOW_GROWTH_PER_CYCLE


def _has_bw(entry: QueueEntry2v2) -> bool:
    return (
        entry["pure_bw_leader_race"] is not None
        and entry["pure_bw_member_race"] is not None
    )


def _has_sc2(entry: QueueEntry2v2) -> bool:
    return (
        entry["pure_sc2_leader_race"] is not None
        and entry["pure_sc2_member_race"] is not None
    )


def _has_mixed(entry: QueueEntry2v2) -> bool:
    return (
        entry["mixed_leader_race"] is not None
        and entry["mixed_member_race"] is not None
    )


def _compatible(a: QueueEntry2v2, b: QueueEntry2v2) -> bool:
    return (
        (_has_bw(a) and _has_sc2(b))
        or (_has_sc2(a) and _has_bw(b))
        or (_has_mixed(a) and _has_mixed(b))
    )


# ---------------------------------------------------------------------------
# Cost matrix
# ---------------------------------------------------------------------------


def _build_cost_matrix(teams: list[QueueEntry2v2]) -> list[list[float]]:
    """Build a symmetric n×n cost matrix over all teams.

    cost[i][j] holds the match score if teams i and j are compatible and
    within each other's MMR window; _SENTINEL otherwise.  The diagonal is
    always _SENTINEL (no self-match).
    """
    n = len(teams)
    cost: list[list[float]] = [[_SENTINEL] * n for _ in range(n)]

    for i in range(n):
        a = teams[i]
        a_window = _max_mmr_diff(a["wait_cycles"])
        for j in range(i + 1, n):
            b = teams[j]
            if not _compatible(a, b):
                continue
            diff = abs(a["team_mmr"] - b["team_mmr"])
            b_window = _max_mmr_diff(b["wait_cycles"])
            if diff > a_window and diff > b_window:
                continue
            wait_factor = max(a["wait_cycles"], b["wait_cycles"])
            score = (diff**2) - ((2**wait_factor) * WAIT_PRIORITY_COEFFICIENT)
            cost[i][j] = score
            cost[j][i] = score  # keep symmetric

    return cost


# ---------------------------------------------------------------------------
# O(n³) Hungarian algorithm (Kuhn–Munkres) — identical to 1v1
# ---------------------------------------------------------------------------


def _hungarian_minimize(cost: list[list[float]], n: int) -> list[int]:
    """Minimum-cost assignment for an *n × n* cost matrix.

    Returns a list *assignment* of length *n* where ``assignment[i]`` is the
    column assigned to row *i*.  Uses the shortest-augmenting-path variant
    which runs in O(n³) time.
    """
    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        min_to = [INF] * (n + 1)
        used = [False] * (n + 1)

        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = -1

            for j in range(1, n + 1):
                if used[j]:
                    continue
                reduced = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if reduced < min_to[j]:
                    min_to[j] = reduced
                    way[j] = j0
                if min_to[j] < delta:
                    delta = min_to[j]
                    j1 = j

            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    min_to[j] -= delta

            j0 = j1
            if p[j0] == 0:
                break

        while j0:
            p[j0] = p[way[j0]]
            j0 = way[j0]

    result = [-1] * n
    for j in range(1, n + 1):
        if p[j] != 0:
            result[p[j] - 1] = j - 1
    return result


# ---------------------------------------------------------------------------
# Composition resolution → MatchCandidate2v2
# ---------------------------------------------------------------------------

# Each option tuple: (team_1, team_2, t1_p1_race, t1_p2_race, t2_p1_race, t2_p2_race)
# For BW-SC2 matches team_1 is always the BW team (player_1=leader, player_2=member).
_ResolvedOption = tuple[QueueEntry2v2, QueueEntry2v2, str, str, str, str]


def _resolve_to_candidate(
    a: QueueEntry2v2,
    b: QueueEntry2v2,
) -> MatchCandidate2v2:
    """Choose a composition for a compatible pair and build the ``MatchCandidate2v2``.

    Races are resolved directly — no intermediate token.  When multiple
    compositions or role assignments are valid, one is chosen randomly so no
    comp is systematically favoured.

    Within each team, the leader (``discord_uid`` / ``player_name``) is
    player_1 and the member (``party_member_*``) is player_2.
    """
    options: list[_ResolvedOption] = []

    # BW-SC2: a is BW team, b is SC2 team.
    if _has_bw(a) and _has_sc2(b):
        if a["pure_bw_leader_race"] is None or a["pure_bw_member_race"] is None:
            raise ValueError(f"Team {a['discord_uid']} declared BW but has None races")
        if b["pure_sc2_leader_race"] is None or b["pure_sc2_member_race"] is None:
            raise ValueError(f"Team {b['discord_uid']} declared SC2 but has None races")
        options.append(
            (
                a,
                b,
                a["pure_bw_leader_race"],
                a["pure_bw_member_race"],
                b["pure_sc2_leader_race"],
                b["pure_sc2_member_race"],
            )
        )
    # BW-SC2: b is BW team, a is SC2 team.
    if _has_sc2(a) and _has_bw(b):
        if b["pure_bw_leader_race"] is None or b["pure_bw_member_race"] is None:
            raise ValueError(f"Team {b['discord_uid']} declared BW but has None races")
        if a["pure_sc2_leader_race"] is None or a["pure_sc2_member_race"] is None:
            raise ValueError(f"Team {a['discord_uid']} declared SC2 but has None races")
        options.append(
            (
                b,
                a,
                b["pure_bw_leader_race"],
                b["pure_bw_member_race"],
                a["pure_sc2_leader_race"],
                a["pure_sc2_member_race"],
            )
        )
    # BW + SC2 vs BW + SC2: caller order preserved.
    if _has_mixed(a) and _has_mixed(b):
        if a["mixed_leader_race"] is None or a["mixed_member_race"] is None:
            raise ValueError(
                f"Team {a['discord_uid']} declared BW + SC2 but has None races"
            )
        if b["mixed_leader_race"] is None or b["mixed_member_race"] is None:
            raise ValueError(
                f"Team {b['discord_uid']} declared BW + SC2 but has None races"
            )
        options.append(
            (
                a,
                b,
                a["mixed_leader_race"],
                a["mixed_member_race"],
                b["mixed_leader_race"],
                b["mixed_member_race"],
            )
        )

    team_1, team_2, t1_p1_race, t1_p2_race, t2_p1_race, t2_p2_race = random.choice(
        options
    )

    return MatchCandidate2v2(
        team_1_player_1_discord_uid=team_1["discord_uid"],
        team_1_player_2_discord_uid=team_1["party_member_discord_uid"],
        team_1_player_1_name=team_1["player_name"],
        team_1_player_2_name=team_1["party_member_name"],
        team_1_player_1_race=t1_p1_race,
        team_1_player_2_race=t1_p2_race,
        team_1_player_1_nationality=team_1["nationality"],
        team_1_player_2_nationality=team_1["member_nationality"],
        team_1_player_1_location=team_1["location"],
        team_1_player_2_location=team_1["member_location"],
        team_1_mmr=team_1["team_mmr"],
        team_1_letter_rank=team_1["team_letter_rank"],
        team_1_map_vetoes=list(team_1["map_vetoes"]),
        team_2_player_1_discord_uid=team_2["discord_uid"],
        team_2_player_2_discord_uid=team_2["party_member_discord_uid"],
        team_2_player_1_name=team_2["player_name"],
        team_2_player_2_name=team_2["party_member_name"],
        team_2_player_1_race=t2_p1_race,
        team_2_player_2_race=t2_p2_race,
        team_2_player_1_nationality=team_2["nationality"],
        team_2_player_2_nationality=team_2["member_nationality"],
        team_2_player_1_location=team_2["location"],
        team_2_player_2_location=team_2["member_location"],
        team_2_mmr=team_2["team_mmr"],
        team_2_letter_rank=team_2["team_letter_rank"],
        team_2_map_vetoes=list(team_2["map_vetoes"]),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_matchmaking_wave_2v2(
    queue: list[QueueEntry2v2],
) -> tuple[list[QueueEntry2v2], list[MatchCandidate2v2]]:
    """Execute one 2v2 matchmaking wave.

    Parameters
    ----------
    queue:
        Current queue entries (one per party).  **Not mutated.**

    Returns
    -------
    remaining:
        Entries for teams not matched this wave, with ``wait_cycles``
        incremented by 1.
    matches:
        Newly formed match candidates.
    """
    if len(queue) < 2:
        early_remaining: list[QueueEntry2v2] = deepcopy(queue)
        for e in early_remaining:
            e["wait_cycles"] = e["wait_cycles"] + 1
        return early_remaining, []

    entries: list[QueueEntry2v2] = deepcopy(queue)
    for e in entries:
        e["wait_cycles"] = e["wait_cycles"] + 1

    n = len(entries)
    cost = _build_cost_matrix(entries)
    col_for_row = _hungarian_minimize(cost, n)

    # Extract unique matched pairs.  The cost matrix is symmetric so the
    # Hungarian may return both (i→j) and (j→i); deduplicating by canonical
    # pair (min, max) ensures each match is processed exactly once.
    seen_pairs: set[tuple[int, int]] = set()
    matched_uids: set[int] = set()
    match_candidates: list[MatchCandidate2v2] = []

    for i, j in enumerate(col_for_row):
        if j < 0 or j >= n:
            continue
        if cost[i][j] >= _SENTINEL:
            continue
        pair = (min(i, j), max(i, j))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        team_a = entries[i]
        team_b = entries[j]
        match_candidates.append(_resolve_to_candidate(team_a, team_b))
        matched_uids.add(team_a["discord_uid"])
        matched_uids.add(team_b["discord_uid"])

    remaining: list[QueueEntry2v2] = [
        e for e in entries if e["discord_uid"] not in matched_uids
    ]
    return remaining, match_candidates
