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
Unlike the 1v1 matchmaker there is no pre-assignment pool equalization step.
Compatibility is checked per-pair instead:

    compatible(A, B) if any of:
      A declared pure_bw  AND B declared pure_sc2  →  BW+BW vs SC2+SC2, A=BW
      A declared pure_sc2 AND B declared pure_bw   →  BW+BW vs SC2+SC2, A=SC2
      A declared mixed    AND B declared mixed      →  mixed vs mixed

Incompatible pairs carry infinite cost and are excluded from the Hungarian
algorithm.  When a pair is valid under multiple match types (e.g. A has
pure_bw + mixed, B has pure_sc2 + mixed), one type is chosen randomly so
the cost function stays pure.

Teams are sorted by ``team_mmr`` and split into two interleaved sides
(even / odd rank), making adjacent-MMR teams natural bipartite opponents.
The same Hungarian algorithm as 1v1 handles optimal pairing.
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

# ---------------------------------------------------------------------------
# Match type tokens
# ---------------------------------------------------------------------------

_BW_SC2 = "bw_sc2"  # team A plays pure BW, team B plays pure SC2
_SC2_BW = "sc2_bw"  # team A plays pure SC2, team B plays pure BW
_MIXED = "mixed"  # both teams play their mixed comp

# Sentinel cost for incompatible / padding cells.
_SENTINEL: float = 1e18


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _max_mmr_diff(wait_cycles: int) -> int:
    return BASE_MMR_WINDOW + wait_cycles * MMR_WINDOW_GROWTH_PER_CYCLE


def _has_bw(entry: QueueEntry2v2) -> bool:
    return entry["pure_bw_leader_race"] is not None


def _has_sc2(entry: QueueEntry2v2) -> bool:
    return entry["pure_sc2_leader_race"] is not None


def _has_mixed(entry: QueueEntry2v2) -> bool:
    return entry["mixed_leader_race"] is not None


# ---------------------------------------------------------------------------
# Compatibility
# ---------------------------------------------------------------------------


def _compatible_match_types(a: QueueEntry2v2, b: QueueEntry2v2) -> list[str]:
    """Return all valid match types for this pair.

    Returns an empty list if the two teams cannot be matched at all.
    """
    types: list[str] = []
    if _has_bw(a) and _has_sc2(b):
        types.append(_BW_SC2)
    if _has_sc2(a) and _has_bw(b):
        types.append(_SC2_BW)
    if _has_mixed(a) and _has_mixed(b):
        types.append(_MIXED)
    return types


# ---------------------------------------------------------------------------
# Build candidate pairs
# ---------------------------------------------------------------------------


def _build_candidates(
    side_a: list[QueueEntry2v2],
    side_b: list[QueueEntry2v2],
) -> list[tuple[float, QueueEntry2v2, QueueEntry2v2, str]]:
    """Return ``(score, a, b, match_type)`` for every compatible pair within
    either team's MMR window.

    The score formula mirrors 1v1::

        wait_factor = max(a.wait_cycles, b.wait_cycles)
        score       = mmr_diff² − 2^wait_factor × WAIT_PRIORITY_COEFFICIENT

    Incompatible pairs are silently skipped; they will never appear in the
    cost matrix and therefore cannot be selected by the Hungarian algorithm.
    When a pair is valid under multiple match types, one is chosen randomly
    so that the caller receives a single deterministic cost entry per pair.
    """
    candidates: list[tuple[float, QueueEntry2v2, QueueEntry2v2, str]] = []

    for a in side_a:
        a_window = _max_mmr_diff(a["wait_cycles"])
        for b in side_b:
            if a["discord_uid"] == b["discord_uid"]:
                continue

            diff = abs(a["team_mmr"] - b["team_mmr"])
            b_window = _max_mmr_diff(b["wait_cycles"])
            if diff > a_window and diff > b_window:
                continue

            match_types = _compatible_match_types(a, b)
            if not match_types:
                continue

            wait_factor = max(a["wait_cycles"], b["wait_cycles"])
            score = (diff**2) - ((2**wait_factor) * WAIT_PRIORITY_COEFFICIENT)
            match_type = random.choice(match_types)
            candidates.append((score, a, b, match_type))

    return candidates


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
# Optimal pair selection via Hungarian algorithm
# ---------------------------------------------------------------------------


def _select_optimal(
    candidates: list[tuple[float, QueueEntry2v2, QueueEntry2v2, str]],
) -> list[tuple[QueueEntry2v2, QueueEntry2v2, str]]:
    """Find the minimum-weight maximum-cardinality bipartite matching.

    Returns a list of ``(team_a, team_b, match_type)`` tuples.
    """
    if not candidates:
        return []

    a_by_uid: dict[int, QueueEntry2v2] = {}
    b_by_uid: dict[int, QueueEntry2v2] = {}
    # For each (a_uid, b_uid) pair, track the best (lowest) score and its type.
    best_score: dict[tuple[int, int], float] = {}
    best_type: dict[tuple[int, int], str] = {}

    for score, a, b, match_type in candidates:
        a_by_uid[a["discord_uid"]] = a
        b_by_uid[b["discord_uid"]] = b
        key = (a["discord_uid"], b["discord_uid"])
        if key not in best_score or score < best_score[key]:
            best_score[key] = score
            best_type[key] = match_type

    a_uids = sorted(a_by_uid)
    b_uids = sorted(b_by_uid)
    n_a = len(a_uids)
    n_b = len(b_uids)

    if n_a == 0 or n_b == 0:
        return []

    a_idx = {uid: i for i, uid in enumerate(a_uids)}
    b_idx = {uid: i for i, uid in enumerate(b_uids)}

    n = max(n_a, n_b)
    cost: list[list[float]] = [[_SENTINEL] * n for _ in range(n)]

    for (a_uid, b_uid), score in best_score.items():
        i = a_idx[a_uid]
        j = b_idx[b_uid]
        if score < cost[i][j]:
            cost[i][j] = score

    col_for_row = _hungarian_minimize(cost, n)

    matches: list[tuple[QueueEntry2v2, QueueEntry2v2, str]] = []
    for i, j in enumerate(col_for_row):
        if i >= n_a or j < 0 or j >= n_b:
            continue
        if cost[i][j] >= _SENTINEL:
            continue
        a_uid = a_uids[i]
        b_uid = b_uids[j]
        match_type = best_type[(a_uid, b_uid)]
        matches.append((a_by_uid[a_uid], b_by_uid[b_uid], match_type))

    return matches


# ---------------------------------------------------------------------------
# Convert matched pair to MatchCandidate2v2
# ---------------------------------------------------------------------------


def _to_match_candidate(
    team_a: QueueEntry2v2,
    team_b: QueueEntry2v2,
    match_type: str,
) -> MatchCandidate2v2:
    """Build a ``MatchCandidate2v2`` from a matched pair.

    Race assignment by match type:
    - ``_BW_SC2``: team A uses their pure BW comp, team B uses pure SC2 comp.
    - ``_SC2_BW``: team A uses their pure SC2 comp, team B uses pure BW comp.
    - ``_MIXED``:  both teams use their mixed comp.

    In all cases team A becomes team_1, team B becomes team_2.
    Within each team, the leader (discord_uid / player_name) is player_1 and
    the member (party_member_*) is player_2.
    """
    if match_type == _BW_SC2:
        t1_p1_race = team_a["pure_bw_leader_race"]
        t1_p2_race = team_a["pure_bw_member_race"]
        t2_p1_race = team_b["pure_sc2_leader_race"]
        t2_p2_race = team_b["pure_sc2_member_race"]
    elif match_type == _SC2_BW:
        t1_p1_race = team_a["pure_sc2_leader_race"]
        t1_p2_race = team_a["pure_sc2_member_race"]
        t2_p1_race = team_b["pure_bw_leader_race"]
        t2_p2_race = team_b["pure_bw_member_race"]
    else:  # _MIXED
        t1_p1_race = team_a["mixed_leader_race"]
        t1_p2_race = team_a["mixed_member_race"]
        t2_p1_race = team_b["mixed_leader_race"]
        t2_p2_race = team_b["mixed_member_race"]

    if t1_p1_race is None or t1_p2_race is None:
        raise ValueError(
            f"Team {team_a['discord_uid']} has no races for match_type={match_type}"
        )
    if t2_p1_race is None or t2_p2_race is None:
        raise ValueError(
            f"Team {team_b['discord_uid']} has no races for match_type={match_type}"
        )

    return MatchCandidate2v2(
        team_1_player_1_discord_uid=team_a["discord_uid"],
        team_1_player_2_discord_uid=team_a["party_member_discord_uid"],
        team_1_player_1_name=team_a["player_name"],
        team_1_player_2_name=team_a["party_member_name"],
        team_1_player_1_race=t1_p1_race,
        team_1_player_2_race=t1_p2_race,
        team_1_player_1_nationality=team_a["nationality"],
        team_1_player_2_nationality=team_a["member_nationality"],
        team_1_player_1_location=team_a["location"],
        team_1_player_2_location=team_a["member_location"],
        team_1_mmr=team_a["team_mmr"],
        team_1_letter_rank=team_a["team_letter_rank"],
        team_1_map_vetoes=list(team_a["map_vetoes"]),
        team_2_player_1_discord_uid=team_b["discord_uid"],
        team_2_player_2_discord_uid=team_b["party_member_discord_uid"],
        team_2_player_1_name=team_b["player_name"],
        team_2_player_2_name=team_b["party_member_name"],
        team_2_player_1_race=t2_p1_race,
        team_2_player_2_race=t2_p2_race,
        team_2_player_1_nationality=team_b["nationality"],
        team_2_player_2_nationality=team_b["member_nationality"],
        team_2_player_1_location=team_b["location"],
        team_2_player_2_location=team_b["member_location"],
        team_2_mmr=team_b["team_mmr"],
        team_2_letter_rank=team_b["team_letter_rank"],
        team_2_map_vetoes=list(team_b["map_vetoes"]),
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

    # Sort by team_mmr and split into two interleaved sides so that
    # adjacent-MMR teams are natural bipartite opponents.
    entries.sort(key=lambda e: e["team_mmr"])
    side_a = entries[0::2]  # even-ranked (lower MMR)
    side_b = entries[1::2]  # odd-ranked (higher MMR)

    candidates = _build_candidates(side_a, side_b)
    matched_pairs = _select_optimal(candidates)

    matched_uids: set[int] = set()
    match_candidates: list[MatchCandidate2v2] = []

    for team_a, team_b, match_type in matched_pairs:
        if team_a["discord_uid"] == team_b["discord_uid"]:
            continue
        match_candidates.append(_to_match_candidate(team_a, team_b, match_type))
        matched_uids.add(team_a["discord_uid"])
        matched_uids.add(team_b["discord_uid"])

    remaining: list[QueueEntry2v2] = [
        e for e in entries if e["discord_uid"] not in matched_uids
    ]
    return remaining, match_candidates
