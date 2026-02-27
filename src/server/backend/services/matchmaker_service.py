"""
Stateless 1 v 1 matchmaking service.

Single entry point: ``run_matchmaking_wave``

Accepts a list of ``QueueEntry1v1`` objects and returns:
  - a list of ``QueueEntry1v1`` objects for players still waiting, with
    ``wait_cycles`` incremented by 1 for every unmatched player, and
  - a list of ``MatchCandidate1v1`` objects for newly formed matches.

No global state, no singletons, no I/O, no mutation of the input list.
"""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional, Tuple

from server.backend.types.state_types import MatchCandidate1v1, QueueEntry1v1

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

# Base MMR window: two players may be matched when their MMR difference is
# at most  BASE_MMR_WINDOW + wait_cycles * MMR_WINDOW_GROWTH_PER_CYCLE
BASE_MMR_WINDOW: int = 100
MMR_WINDOW_GROWTH_PER_CYCLE: int = 50

# When scoring candidate pairs a lower score is better.
# score = mmr_diff² − (combined_wait_cycles × WAIT_PRIORITY_COEFFICIENT)
WAIT_PRIORITY_COEFFICIENT: float = 20.0

# Number of adjacent-swap refinement passes after the initial greedy match
# selection (least-squares improvement).
REFINEMENT_PASSES: int = 2

# When rebalancing "both-race" players between the BW and SC2 pools, only
# attempt a swap if the mean-MMR difference between the two pools exceeds
# this threshold.
BALANCE_THRESHOLD_MMR: int = 50

# Fallback MMR used when a player's MMR is ``None``.
DEFAULT_MMR: int = 1500


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _mmr_or_default(value: Optional[int]) -> int:
    return value if value is not None else DEFAULT_MMR


def _max_mmr_diff(wait_cycles: int) -> int:
    """Allowed MMR difference for a player who has waited *wait_cycles* waves."""
    return BASE_MMR_WINDOW + wait_cycles * MMR_WINDOW_GROWTH_PER_CYCLE


def _has_bw(entry: QueueEntry1v1) -> bool:
    return entry["bw_race"] is not None


def _has_sc2(entry: QueueEntry1v1) -> bool:
    return entry["sc2_race"] is not None


def _effective_mmr(entry: QueueEntry1v1, *, bw: bool) -> int:
    return _mmr_or_default(entry["bw_mmr"] if bw else entry["sc2_mmr"])


def _race_for_match(entry: QueueEntry1v1, *, bw: bool) -> Optional[str]:
    return entry["bw_race"] if bw else entry["sc2_race"]


def _skill_bias(entry: QueueEntry1v1) -> int:
    """Positive → stronger at BW, negative → stronger at SC2."""
    return _mmr_or_default(entry["bw_mmr"]) - _mmr_or_default(entry["sc2_mmr"])


# ---------------------------------------------------------------------------
# Categorise queue entries
# ---------------------------------------------------------------------------

def _categorise(
    entries: list[QueueEntry1v1],
) -> Tuple[list[QueueEntry1v1], list[QueueEntry1v1], list[QueueEntry1v1]]:
    """Split entries into (bw_only, sc2_only, both) lists sorted by MMR."""
    bw_only: list[QueueEntry1v1] = []
    sc2_only: list[QueueEntry1v1] = []
    both: list[QueueEntry1v1] = []

    for e in entries:
        has_bw = _has_bw(e)
        has_sc2 = _has_sc2(e)
        if has_bw and not has_sc2:
            bw_only.append(e)
        elif has_sc2 and not has_bw:
            sc2_only.append(e)
        elif has_bw and has_sc2:
            both.append(e)
        else:
            # This should never happen
            print(f"QueueEntry1v1 {e['discord_uid']} has no race")

    bw_only.sort(key=lambda p: _mmr_or_default(p["bw_mmr"]), reverse=True)
    sc2_only.sort(key=lambda p: _mmr_or_default(p["sc2_mmr"]), reverse=True)
    both.sort(
        key=lambda p: max(_mmr_or_default(p["bw_mmr"]), _mmr_or_default(p["sc2_mmr"])),
        reverse=True,
    )
    return bw_only, sc2_only, both


# ---------------------------------------------------------------------------
# Equalise BW / SC2 pools using "both" players
# ---------------------------------------------------------------------------

def _equalise(
    bw_list: list[QueueEntry1v1],
    sc2_list: list[QueueEntry1v1],
    both_list: list[QueueEntry1v1],
) -> Tuple[list[QueueEntry1v1], list[QueueEntry1v1]]:
    """Assign *both_list* players into *bw_list* or *sc2_list* to balance sizes
    and, as a secondary objective, skill.  Returns new lists; inputs are not
    mutated."""
    bw = list(bw_list)
    sc2 = list(sc2_list)
    remaining = sorted(both_list, key=_skill_bias)  # SC2-leaning first

    # Special case: both dedicated pools empty – split evenly by bias.
    if not bw and not sc2 and remaining:
        mid = len(remaining) // 2
        sc2 = remaining[:mid]
        bw = remaining[mid:]
        return bw, sc2

    if not remaining:
        return bw, sc2

    # Phase 1 – hard population balance.
    delta = len(bw) - len(sc2)
    if delta < 0:
        # BW needs more – take the most BW-biased (end of list).
        for _ in range(min(abs(delta), len(remaining))):
            bw.append(remaining.pop())
    elif delta > 0:
        # SC2 needs more – take the most SC2-biased (start of list).
        for _ in range(min(delta, len(remaining))):
            sc2.append(remaining.pop(0))

    # Phase 2 – distribute leftovers, alternating to keep sizes balanced.
    while remaining:
        if len(bw) < len(sc2):
            bw.append(remaining.pop())
        elif len(bw) > len(sc2):
            sc2.append(remaining.pop(0))
        else:
            if remaining:
                sc2.append(remaining.pop(0))
            if remaining:
                bw.append(remaining.pop())

    # Phase 3 – soft skill rebalancing: if the mean-MMR gap is too large,
    # swap a single neutral "both" player across pools.
    if bw and sc2:
        bw_mean = sum(_mmr_or_default(p["bw_mmr"]) for p in bw) / len(bw)
        sc2_mean = sum(_mmr_or_default(p["sc2_mmr"]) for p in sc2) / len(sc2)
        mmr_delta = bw_mean - sc2_mean
        pop_diff = abs(len(bw) - len(sc2))

        if abs(mmr_delta) > BALANCE_THRESHOLD_MMR:
            if mmr_delta > BALANCE_THRESHOLD_MMR:
                # BW pool is stronger – move a neutral "both" player to SC2.
                candidates = sorted(
                    [p for p in bw if _has_bw(p) and _has_sc2(p)],
                    key=lambda p: abs(_skill_bias(p)),
                )
                if candidates:
                    new_pop_diff = abs((len(bw) - 1) - (len(sc2) + 1))
                    if new_pop_diff <= pop_diff:
                        player = candidates[0]
                        bw.remove(player)
                        sc2.append(player)
            elif mmr_delta < -BALANCE_THRESHOLD_MMR:
                candidates = sorted(
                    [p for p in sc2 if _has_bw(p) and _has_sc2(p)],
                    key=lambda p: abs(_skill_bias(p)),
                )
                if candidates:
                    new_pop_diff = abs((len(bw) + 1) - (len(sc2) - 1))
                    if new_pop_diff <= pop_diff:
                        player = candidates[0]
                        sc2.remove(player)
                        bw.append(player)

    return bw, sc2


# ---------------------------------------------------------------------------
# Priority-based pre-filter
# ---------------------------------------------------------------------------

def _filter_by_priority(
    lead: list[QueueEntry1v1],
    follow: list[QueueEntry1v1],
) -> Tuple[list[QueueEntry1v1], list[QueueEntry1v1]]:
    """If one side is larger, trim it to match the smaller side, keeping the
    entries with the highest ``wait_cycles``."""
    if len(lead) == len(follow):
        return lead, follow

    if len(lead) > len(follow):
        trimmed = sorted(lead, key=lambda p: p["wait_cycles"], reverse=True)[: len(follow)]
        return trimmed, follow
    else:
        trimmed = sorted(follow, key=lambda p: p["wait_cycles"], reverse=True)[: len(lead)]
        return lead, trimmed


# ---------------------------------------------------------------------------
# Build candidate pairs and greedy selection
# ---------------------------------------------------------------------------

def _build_candidates(
    lead: list[QueueEntry1v1],
    follow: list[QueueEntry1v1],
    lead_is_bw: bool,
) -> list[Tuple[float, QueueEntry1v1, QueueEntry1v1, int]]:
    """Return ``(score, lead_entry, follow_entry, mmr_diff)`` for every valid
    pairing within either player's MMR window."""
    candidates: list[Tuple[float, QueueEntry1v1, QueueEntry1v1, int]] = []

    for le in lead:
        le_mmr = _effective_mmr(le, bw=lead_is_bw)
        le_window = _max_mmr_diff(le["wait_cycles"])

        for fe in follow:
            if le["discord_uid"] == fe["discord_uid"]:
                continue

            fe_mmr = _effective_mmr(fe, bw=not lead_is_bw)
            fe_window = _max_mmr_diff(fe["wait_cycles"])
            diff = abs(le_mmr - fe_mmr)

            if diff <= le_window or diff <= fe_window:
                wait_sum = le["wait_cycles"] + fe["wait_cycles"]
                score = (diff ** 2) - (wait_sum * WAIT_PRIORITY_COEFFICIENT)
                candidates.append((score, le, fe, diff))

    return candidates


def _select_greedy(
    candidates: list[Tuple[float, QueueEntry1v1, QueueEntry1v1, int]],
) -> list[Tuple[QueueEntry1v1, QueueEntry1v1]]:
    """Greedily pick the best non-overlapping pairs from sorted candidates."""
    candidates_sorted = sorted(candidates, key=lambda c: c[0])
    used_lead: set[int] = set()
    used_follow: set[int] = set()
    matches: list[Tuple[QueueEntry1v1, QueueEntry1v1]] = []

    for _score, le, fe, _diff in candidates_sorted:
        if le["discord_uid"] not in used_lead and fe["discord_uid"] not in used_follow:
            matches.append((le, fe))
            used_lead.add(le["discord_uid"])
            used_follow.add(fe["discord_uid"])

    return matches


# ---------------------------------------------------------------------------
# Least-squares refinement (adjacent swaps)
# ---------------------------------------------------------------------------

def _refine_matches(
    matches: list[Tuple[QueueEntry1v1, QueueEntry1v1]],
    lead_is_bw: bool,
) -> list[Tuple[QueueEntry1v1, QueueEntry1v1]]:
    """Perform adjacent-swap passes to reduce the total squared MMR error."""
    if len(matches) < 2:
        return matches

    result = list(matches)

    for _ in range(REFINEMENT_PASSES):
        swapped = False
        for i in range(len(result) - 1):
            l1, f1 = result[i]
            l2, f2 = result[i + 1]

            l1_mmr = _effective_mmr(l1, bw=lead_is_bw)
            f1_mmr = _effective_mmr(f1, bw=not lead_is_bw)
            l2_mmr = _effective_mmr(l2, bw=lead_is_bw)
            f2_mmr = _effective_mmr(f2, bw=not lead_is_bw)

            err_before = (l1_mmr - f1_mmr) ** 2 + (l2_mmr - f2_mmr) ** 2
            err_after = (l1_mmr - f2_mmr) ** 2 + (l2_mmr - f1_mmr) ** 2

            if err_after >= err_before:
                continue

            # Prevent self-matches after swap.
            if l1["discord_uid"] == f2["discord_uid"] or l2["discord_uid"] == f1["discord_uid"]:
                continue

            # Ensure both new pairings respect at least one player's window.
            d1 = abs(l1_mmr - f2_mmr)
            d2 = abs(l2_mmr - f1_mmr)
            m1_ok = d1 <= _max_mmr_diff(l1["wait_cycles"]) or d1 <= _max_mmr_diff(f2["wait_cycles"])
            m2_ok = d2 <= _max_mmr_diff(l2["wait_cycles"]) or d2 <= _max_mmr_diff(f1["wait_cycles"])

            if m1_ok and m2_ok:
                result[i] = (l1, f2)
                result[i + 1] = (l2, f1)
                swapped = True

        if not swapped:
            break

    return result


# ---------------------------------------------------------------------------
# Convert internal match tuples to MatchCandidate1v1
# ---------------------------------------------------------------------------

def _to_match_candidate(
    lead_entry: QueueEntry1v1,
    follow_entry: QueueEntry1v1,
    lead_is_bw: bool,
) -> MatchCandidate1v1:
    p1_race = _race_for_match(lead_entry, bw=lead_is_bw)
    p2_race = _race_for_match(follow_entry, bw=not lead_is_bw)

    # These should always be non-None given how categorisation works, but
    # guard defensively.
    assert p1_race is not None, f"Lead player {lead_entry['discord_uid']} has no race for bw={lead_is_bw}"
    assert p2_race is not None, f"Follow player {follow_entry['discord_uid']} has no race for bw={not lead_is_bw}"

    return MatchCandidate1v1(
        player_1_discord_uid=lead_entry["discord_uid"],
        player_2_discord_uid=follow_entry["discord_uid"],
        player_1_name=lead_entry["player_name"],
        player_2_name=follow_entry["player_name"],
        player_1_race=p1_race,
        player_2_race=p2_race,
        player_1_mmr=_effective_mmr(lead_entry, bw=lead_is_bw),
        player_2_mmr=_effective_mmr(follow_entry, bw=not lead_is_bw),
        player_1_map_vetoes=list(lead_entry["map_vetoes"]),
        player_2_map_vetoes=list(follow_entry["map_vetoes"]),
        assigned_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_matchmaking_wave(
    queue: list[QueueEntry1v1],
) -> Tuple[list[QueueEntry1v1], list[MatchCandidate1v1]]:
    """Execute one matchmaking wave.

    Parameters
    ----------
    queue:
        Current queue entries.  **Not mutated.**

    Returns
    -------
    remaining:
        Queue entries for players who were *not* matched.  Each entry's
        ``wait_cycles`` is incremented by 1 relative to the input.
    matches:
        Newly formed match candidates.
    """
    if len(queue) < 2:
        # Not enough players – just increment wait_cycles and return.
        remaining = [
            {**entry, "wait_cycles": entry["wait_cycles"] + 1}
            for entry in queue
        ]
        return remaining, []

    # Deep-copy so we never touch the caller's data.
    entries: list[QueueEntry1v1] = deepcopy(queue)

    # Increment wait_cycles for everyone (this wave counts).
    for e in entries:
        e["wait_cycles"] = e["wait_cycles"] + 1

    # --- Categorise ---------------------------------------------------------
    bw_only, sc2_only, both = _categorise(entries)

    # --- Equalise pools using "both" players --------------------------------
    bw_pool, sc2_pool = _equalise(bw_only, sc2_only, both)

    # Sanity: pools must be disjoint.
    bw_ids = {p["discord_uid"] for p in bw_pool}
    sc2_ids = {p["discord_uid"] for p in sc2_pool}
    assert not (bw_ids & sc2_ids), "Equalisation produced overlapping pools"

    # --- Determine lead / follow and match ----------------------------------
    matched_pairs: list[Tuple[QueueEntry1v1, QueueEntry1v1]] = []
    lead_is_bw: bool = True  # default; may be flipped below

    if bw_pool and sc2_pool:
        if len(bw_pool) <= len(sc2_pool):
            lead, follow = bw_pool, sc2_pool
            lead_is_bw = True
        else:
            lead, follow = sc2_pool, bw_pool
            lead_is_bw = False

        lead, follow = _filter_by_priority(lead, follow)
        candidates = _build_candidates(lead, follow, lead_is_bw)
        matched_pairs = _select_greedy(candidates)
        matched_pairs = _refine_matches(matched_pairs, lead_is_bw)

    # --- Build outputs ------------------------------------------------------
    matched_uids: set[int] = set()
    match_candidates: list[MatchCandidate1v1] = []

    for lead_entry, follow_entry in matched_pairs:
        # Final self-match guard (should never trigger).
        if lead_entry["discord_uid"] == follow_entry["discord_uid"]:
            continue

        match_candidates.append(
            _to_match_candidate(lead_entry, follow_entry, lead_is_bw)
        )
        matched_uids.add(lead_entry["discord_uid"])
        matched_uids.add(follow_entry["discord_uid"])

    remaining: list[QueueEntry1v1] = [
        e for e in entries if e["discord_uid"] not in matched_uids
    ]

    return remaining, match_candidates