"""
Stateless 1 v 1 matchmaking service.

Single entry point: ``run_matchmaking_wave``

Accepts a list of ``QueueEntry1v1`` objects and returns:
  - a list of ``QueueEntry1v1`` objects for players still waiting, with
    ``wait_cycles`` incremented by 1 for every unmatched player, and
  - a list of ``MatchCandidate1v1`` objects for newly formed matches.

No global state, no singletons, no I/O, no mutation of the input list.

Algorithm
---------
Inspired by the 2v2 matchmaker: build the entire bipartite cost matrix
first, then let the Hungarian algorithm decide side-commitment globally.

Rows are players that *can* play BW (``bw_only ∪ both``); columns are
players that *can* play SC2 (``sc2_only ∪ both``).  A "Both" player
appears on both axes; the assignment optimiser is responsible for never
selecting them on more than one side.

Each cell ``cost[i][j]`` is finite if:
  - the row and column refer to different players (``discord_uid``), and
  - ``|row.bw_mmr − col.sc2_mmr|`` lies within either player's MMR window.

Otherwise the cell is ``_SENTINEL``.  The matrix is then padded to a
square of side ``max(n_rows, n_cols)`` with ``_SENTINEL`` and fed to the
O(n³) Hungarian algorithm, producing a minimum-weight maximum-cardinality
matching.  Side-commitment for "Both" players falls out of the assignment
automatically.
"""

from copy import deepcopy

from backend.core.config import (
    BASE_MMR_WINDOW,
    DISALLOWED_REGION_PAIRS,
    MMR,
    MMR_WINDOW_GROWTH_PER_CYCLE,
    WAIT_PRIORITY_COEFFICIENT,
)
from backend.domain_types.ephemeral import MatchCandidate1v1, QueueEntry1v1

# Fallback MMR used when a player's MMR is ``None``.
DEFAULT_MMR: int = MMR["default"]

# Sentinel cost for infeasible / padding / self-match cells.  Must exceed
# the absolute value of any valid score.
_SENTINEL: float = 1e18


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _mmr_or_default(value: int | None) -> int:
    return value if value is not None else DEFAULT_MMR


def _max_mmr_diff(wait_cycles: int) -> int:
    """Allowed MMR difference for a player who has waited *wait_cycles* waves."""
    return BASE_MMR_WINDOW + wait_cycles * MMR_WINDOW_GROWTH_PER_CYCLE


def _has_bw(entry: QueueEntry1v1) -> bool:
    return entry["bw_race"] is not None


def _has_sc2(entry: QueueEntry1v1) -> bool:
    return entry["sc2_race"] is not None


def _regions_disallowed(loc_a: str | None, loc_b: str | None) -> bool:
    """Return True if this region pair is in ``DISALLOWED_REGION_PAIRS``.

    Players with an unknown ``location`` (``None``) are never blocked —
    we have no information to act on, and ``_match.py`` will fall back
    to the opponent's location at server-resolution time.
    """
    if loc_a is None or loc_b is None:
        return False
    return frozenset({loc_a, loc_b}) in DISALLOWED_REGION_PAIRS


# ---------------------------------------------------------------------------
# Cost matrix
# ---------------------------------------------------------------------------


def _build_cost_matrix(
    bw_rows: list[QueueEntry1v1],
    sc2_cols: list[QueueEntry1v1],
) -> list[list[float]]:
    """Build a bipartite cost matrix padded to a square with ``_SENTINEL``.

    Rows index players that can play BW; columns index players that can
    play SC2.  A "Both" player appears once in each list.  Cells where the
    row and column refer to the same ``discord_uid`` are ``_SENTINEL`` so
    the assignment can never self-match.
    """
    n_rows = len(bw_rows)
    n_cols = len(sc2_cols)
    n = max(n_rows, n_cols)
    cost: list[list[float]] = [[_SENTINEL] * n for _ in range(n)]

    for i in range(n_rows):
        row = bw_rows[i]
        row_mmr = _mmr_or_default(row["bw_mmr"])
        row_window = _max_mmr_diff(row["wait_cycles"])
        for j in range(n_cols):
            col = sc2_cols[j]
            if row["discord_uid"] == col["discord_uid"]:
                continue
            if _regions_disallowed(row["location"], col["location"]):
                continue
            col_mmr = _mmr_or_default(col["sc2_mmr"])
            diff = abs(row_mmr - col_mmr)
            col_window = _max_mmr_diff(col["wait_cycles"])
            if diff > row_window and diff > col_window:
                continue
            wait_factor = max(row["wait_cycles"], col["wait_cycles"])
            score = (diff**2) - ((2**wait_factor) * WAIT_PRIORITY_COEFFICIENT)
            cost[i][j] = score

    return cost


# ---------------------------------------------------------------------------
# O(n³) Hungarian algorithm (Kuhn–Munkres)
# ---------------------------------------------------------------------------


def _hungarian_minimize(cost: list[list[float]], n: int) -> list[int]:
    """Minimum-cost assignment for an *n × n* cost matrix.

    Returns a list *assignment* of length *n* where ``assignment[i]`` is the
    column assigned to row *i*.  Uses the shortest-augmenting-path variant
    which runs in O(n³) time — perfectly adequate for n ≤ 100.
    """
    INF = float("inf")

    # Dual variables (potentials), 1-indexed.
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    # p[j] = row currently assigned to column j (1-indexed; 0 = free).
    p = [0] * (n + 1)
    # way[j] = predecessor column on the shortest-path tree.
    way = [0] * (n + 1)

    for i in range(1, n + 1):
        # Introduce row i; start augmenting from virtual column 0.
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

            # Update potentials along the alternating tree.
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    min_to[j] -= delta

            j0 = j1
            if p[j0] == 0:
                break

        # Unwind the augmenting path.
        while j0:
            p[j0] = p[way[j0]]
            j0 = way[j0]

    # Convert to 0-indexed result.
    result = [-1] * n
    for j in range(1, n + 1):
        if p[j] != 0:
            result[p[j] - 1] = j - 1

    return result


# ---------------------------------------------------------------------------
# Convert internal match tuples to MatchCandidate1v1
# ---------------------------------------------------------------------------


def _to_match_candidate(
    bw_entry: QueueEntry1v1,
    sc2_entry: QueueEntry1v1,
) -> MatchCandidate1v1:
    p1_race = bw_entry["bw_race"]
    p2_race = sc2_entry["sc2_race"]

    if p1_race is None:
        raise ValueError(f"BW-side player {bw_entry['discord_uid']} has no bw_race")
    if p2_race is None:
        raise ValueError(f"SC2-side player {sc2_entry['discord_uid']} has no sc2_race")

    return MatchCandidate1v1(
        player_1_discord_uid=bw_entry["discord_uid"],
        player_2_discord_uid=sc2_entry["discord_uid"],
        player_1_name=bw_entry["player_name"],
        player_2_name=sc2_entry["player_name"],
        player_1_race=p1_race,
        player_2_race=p2_race,
        player_1_mmr=_mmr_or_default(bw_entry["bw_mmr"]),
        player_2_mmr=_mmr_or_default(sc2_entry["sc2_mmr"]),
        player_1_location=bw_entry["location"],
        player_2_location=sc2_entry["location"],
        player_1_map_vetoes=list(bw_entry["map_vetoes"]),
        player_2_map_vetoes=list(sc2_entry["map_vetoes"]),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_matchmaking_wave(
    queue: list[QueueEntry1v1],
) -> tuple[list[QueueEntry1v1], list[MatchCandidate1v1]]:
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
        early_remaining: list[QueueEntry1v1] = deepcopy(queue)
        for e in early_remaining:
            e["wait_cycles"] = e["wait_cycles"] + 1
        return early_remaining, []

    # Deep-copy so we never touch the caller's data.
    entries: list[QueueEntry1v1] = deepcopy(queue)

    # Increment wait_cycles for everyone (this wave counts).
    for e in entries:
        e["wait_cycles"] = e["wait_cycles"] + 1

    # Build BW (row) and SC2 (column) lists.  "Both" players appear in
    # both lists; entries with no race are silently skipped.
    bw_rows: list[QueueEntry1v1] = [e for e in entries if _has_bw(e)]
    sc2_cols: list[QueueEntry1v1] = [e for e in entries if _has_sc2(e)]

    matched_uids: set[int] = set()
    match_candidates: list[MatchCandidate1v1] = []

    if bw_rows and sc2_cols:
        n_rows = len(bw_rows)
        n_cols = len(sc2_cols)
        n = max(n_rows, n_cols)
        cost = _build_cost_matrix(bw_rows, sc2_cols)
        col_for_row = _hungarian_minimize(cost, n)

        for i, j in enumerate(col_for_row):
            if i >= n_rows or j < 0 or j >= n_cols:
                continue
            if cost[i][j] >= _SENTINEL:
                continue
            bw_entry = bw_rows[i]
            sc2_entry = sc2_cols[j]
            # Defensive guards: a player already committed to one side
            # this wave can't appear on the other.
            if bw_entry["discord_uid"] == sc2_entry["discord_uid"]:
                continue
            if bw_entry["discord_uid"] in matched_uids:
                continue
            if sc2_entry["discord_uid"] in matched_uids:
                continue

            match_candidates.append(_to_match_candidate(bw_entry, sc2_entry))
            matched_uids.add(bw_entry["discord_uid"])
            matched_uids.add(sc2_entry["discord_uid"])

    remaining: list[QueueEntry1v1] = [
        e for e in entries if e["discord_uid"] not in matched_uids
    ]

    return remaining, match_candidates
