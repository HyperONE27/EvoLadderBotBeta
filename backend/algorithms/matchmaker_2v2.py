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
For each ordered pair of teams (i, j) with i < j, check compatibility:

    compatible(A, B) if any of:
      A declared pure_bw  AND B declared pure_sc2  →  BW+BW vs SC2+SC2, A=BW
      A declared pure_sc2 AND B declared pure_bw   →  BW+BW vs SC2+SC2, A=SC2
      A declared mixed    AND B declared mixed      →  mixed vs mixed

Incompatible pairs are silently skipped.  Compatible pairs within either
team's MMR window are scored::

    wait_factor = max(a.wait_cycles, b.wait_cycles)
    score       = mmr_diff² − 2^wait_factor × WAIT_PRIORITY_COEFFICIENT

All valid (score, a, b, match_type) candidates are sorted ascending by score
and selected greedily: the best-scoring unmatched pair is taken, both teams
are marked matched, and the process repeats.  This is O(n² log n) and
optimal in practice for the small queue sizes this system targets.

When a pair is valid under multiple match types (e.g. A has pure_bw + mixed,
B has pure_sc2 + mixed), one type is chosen randomly so that the score
remains independent of match-type selection.
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
# Build and select candidates
# ---------------------------------------------------------------------------


def _build_candidates(
    teams: list[QueueEntry2v2],
) -> list[tuple[float, QueueEntry2v2, QueueEntry2v2, str]]:
    """Return ``(score, a, b, match_type)`` for every compatible pair within
    either team's MMR window, considering all (i < j) combinations.

    Incompatible pairs are silently skipped.  When a pair is valid under
    multiple match types, one is chosen randomly.
    """
    candidates: list[tuple[float, QueueEntry2v2, QueueEntry2v2, str]] = []
    n = len(teams)

    for i in range(n):
        a = teams[i]
        a_window = _max_mmr_diff(a["wait_cycles"])
        for j in range(i + 1, n):
            b = teams[j]
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


def _select_greedy(
    candidates: list[tuple[float, QueueEntry2v2, QueueEntry2v2, str]],
) -> list[tuple[QueueEntry2v2, QueueEntry2v2, str]]:
    """Greedily select matches from best score to worst.

    Sorts all candidates ascending by score, then iterates: if neither team
    in a pair has been matched yet, take the pair and mark both as matched.
    """
    candidates_sorted = sorted(candidates, key=lambda c: c[0])
    matched_uids: set[int] = set()
    matches: list[tuple[QueueEntry2v2, QueueEntry2v2, str]] = []

    for _score, a, b, match_type in candidates_sorted:
        if a["discord_uid"] in matched_uids or b["discord_uid"] in matched_uids:
            continue
        matches.append((a, b, match_type))
        matched_uids.add(a["discord_uid"])
        matched_uids.add(b["discord_uid"])

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

    candidates = _build_candidates(entries)
    matched_pairs = _select_greedy(candidates)

    matched_uids: set[int] = set()
    match_candidates: list[MatchCandidate2v2] = []

    for team_a, team_b, match_type in matched_pairs:
        match_candidates.append(_to_match_candidate(team_a, team_b, match_type))
        matched_uids.add(team_a["discord_uid"])
        matched_uids.add(team_b["discord_uid"])

    remaining: list[QueueEntry2v2] = [
        e for e in entries if e["discord_uid"] not in matched_uids
    ]
    return remaining, match_candidates
