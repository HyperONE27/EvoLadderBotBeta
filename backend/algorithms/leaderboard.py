"""Leaderboard computation — pure, stateless, no I/O.

Takes the in-memory ``mmrs_1v1_df`` and ``players_df`` Polars DataFrames and
returns a fully ranked ``list[LeaderboardEntry1v1]``.

Ranking rules:
- All player-race pairs with ``games_played > 0`` are included.
- Sorted by MMR descending, ``last_played_at`` descending as tiebreaker.
- ``ordinal_rank`` — dense rank across **all** entries (active + inactive).
- ``active_ordinal_rank`` — dense rank across active entries only; -1 for inactive.
- Active = ``last_played_at`` within ``LEADERBOARD_INACTIVITY_DAYS`` of now.
- Letter ranks are assigned only to active entries using fixed-percentage
  allocation with a guarantee of at least 1 entry per rank (when population
  permits).  Inactive entries receive letter rank ``"U"``.

Allocation algorithm:
1. If active count >= 7, reserve 1 slot per rank, then distribute remaining
   ``N - 7`` via ``floor(percentage * remaining)``, then distribute leftover
   players using the alpha-style adaptive order.
2. If active count < 7, assign via the same adaptive priority until exhausted.

Adaptive remainder distribution order:
  Middle ranks first: D → C → E → B
  Then adaptively: if F > S+A, give to A first (A → F → S);
                    otherwise give to F first (F → A → S).
"""

from datetime import datetime, timedelta, timezone

import polars as pl

from backend.core.config import LEADERBOARD_INACTIVITY_DAYS
from backend.domain_types.ephemeral import LeaderboardEntry1v1

# Rank percentages (must sum to 1.0).
_RANK_PERCENTAGES: dict[str, float] = {
    "S": 0.01,
    "A": 0.07,
    "B": 0.21,
    "C": 0.21,
    "D": 0.21,
    "E": 0.21,
    "F": 0.08,
}

_RANK_ORDER: list[str] = ["S", "A", "B", "C", "D", "E", "F"]

# Middle ranks get remainders first, then adaptive A/F/S.
_MIDDLE_RANKS: list[str] = ["D", "C", "E", "B"]


def build_leaderboard_1v1(
    mmrs_1v1_df: pl.DataFrame,
    players_df: pl.DataFrame,
) -> list[LeaderboardEntry1v1]:
    """Compute the 1v1 leaderboard from the current DataFrames."""
    df = mmrs_1v1_df.filter(pl.col("games_played") > 0)

    if df.is_empty():
        return []

    # Join nationality from players_df.
    nationality_map = players_df.select("discord_uid", "nationality")
    df = df.join(nationality_map, on="discord_uid", how="left")

    # Sort: highest MMR first, most recent activity as tiebreaker.
    df = df.sort(["mmr", "last_played_at"], descending=[True, True])

    rows = df.select(
        "discord_uid",
        "player_name",
        "race",
        "nationality",
        "mmr",
        "games_played",
        "last_played_at",
    ).to_dicts()

    # --- Ordinal rank (all entries, dense) ---
    ordinal_ranks: list[int] = []
    prev_mmr: int | None = None
    prev_rank = 0
    for idx, row in enumerate(rows):
        mmr_val: int = row["mmr"]
        if mmr_val != prev_mmr:
            prev_rank = idx + 1
            prev_mmr = mmr_val
        ordinal_ranks.append(prev_rank)

    # --- Active / inactive split ---
    cutoff = datetime.now(timezone.utc) - timedelta(days=LEADERBOARD_INACTIVITY_DAYS)

    active_indices: list[int] = []
    inactive_indices: list[int] = []
    for idx, row in enumerate(rows):
        lp = row["last_played_at"]
        if lp is not None and _ensure_utc(lp) >= cutoff:
            active_indices.append(idx)
        else:
            inactive_indices.append(idx)

    # --- Active ordinal rank (active entries only, dense) ---
    active_ordinal_map: dict[int, int] = {}
    a_prev_mmr: int | None = None
    a_prev_rank = 0
    for pos, idx in enumerate(active_indices):
        mmr_val = rows[idx]["mmr"]
        if mmr_val != a_prev_mmr:
            a_prev_rank = pos + 1
            a_prev_mmr = mmr_val
        active_ordinal_map[idx] = a_prev_rank

    # --- Letter rank allocation (active entries only) ---
    total_active = len(active_indices)
    allocations = _calculate_allocations(total_active)

    # Map active list position → letter rank.
    letter_rank_map: dict[int, str] = {}
    active_pos = 0
    for rank_letter in _RANK_ORDER:
        count = allocations[rank_letter]
        for _ in range(count):
            if active_pos < total_active:
                letter_rank_map[active_indices[active_pos]] = rank_letter
                active_pos += 1

    # --- Build final list ---
    entries: list[LeaderboardEntry1v1] = []
    for idx, row in enumerate(rows):
        entries.append(
            LeaderboardEntry1v1(
                discord_uid=row["discord_uid"],
                player_name=row["player_name"],
                ordinal_rank=ordinal_ranks[idx],
                active_ordinal_rank=active_ordinal_map.get(idx, -1),
                letter_rank=letter_rank_map.get(idx, "U"),
                race=row["race"],
                nationality=row["nationality"] or "",
                mmr=row["mmr"],
                games_played=row["games_played"],
                last_played_at=row["last_played_at"],
            )
        )

    return entries


# ---------------------------------------------------------------------------
# Allocation helpers
# ---------------------------------------------------------------------------


def _calculate_allocations(total_active: int) -> dict[str, int]:
    """Calculate how many active players go into each letter rank.

    Guarantees at least 1 player per rank when ``total_active >= 7``.
    """
    num_ranks = len(_RANK_ORDER)

    if total_active == 0:
        return {r: 0 for r in _RANK_ORDER}

    if total_active < num_ranks:
        # Not enough players for every rank — fill via adaptive priority.
        alloc = {r: 0 for r in _RANK_ORDER}
        order = _adaptive_remainder_order(alloc)
        for i in range(total_active):
            alloc[order[i % len(order)]] += 1
        return alloc

    # Reserve 1 per rank, distribute the rest by percentage.
    alloc = {r: 1 for r in _RANK_ORDER}
    remaining_pool = total_active - num_ranks

    # Floor-allocate by percentage.
    floor_alloc: dict[str, int] = {}
    for rank, pct in _RANK_PERCENTAGES.items():
        floor_alloc[rank] = int(remaining_pool * pct)

    for rank in _RANK_ORDER:
        alloc[rank] += floor_alloc[rank]

    allocated = sum(alloc.values())
    leftover = total_active - allocated

    # Distribute leftover via adaptive order.
    order = _adaptive_remainder_order(alloc)
    for i in range(leftover):
        alloc[order[i % len(order)]] += 1

    return alloc


def _adaptive_remainder_order(current_alloc: dict[str, int]) -> list[str]:
    """Return the priority order for distributing remaining players.

    Middle ranks first (D → C → E → B), then adaptive A/F based on
    whether F > S+A, then S last.
    """
    order = list(_MIDDLE_RANKS)

    s_a = current_alloc.get("S", 0) + current_alloc.get("A", 0)
    f = current_alloc.get("F", 0)

    if f > s_a:
        order.extend(["A", "F", "S"])
    else:
        order.extend(["F", "A", "S"])

    return order


def _ensure_utc(dt: datetime) -> datetime:
    """Make a datetime UTC-aware if it isn't already."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
