"""Leaderboard computation — pure, stateless, no I/O.

Takes the in-memory ``mmrs_1v1_df`` and ``players_df`` Polars DataFrames and
returns a fully ranked ``list[LeaderboardEntry1v1]``.

Ranking rules:
- All player-race pairs with ``games_played > 0`` are included.
- Total ordering (no shared ranks except for truly identical rows):
    1. MMR descending
    2. last_played_at descending (more recently played ranks higher)
    3. win_rate (games_won / games_played) descending
    4. nonlose_rate ((games_won + games_drawn) / games_played) descending
    5. games_played descending
    6. player_name ascending (lexicographically earlier ranks higher)
- ``ordinal_rank`` — rank across **all** entries (active + inactive).
- ``active_ordinal_rank`` — rank across active entries only; -1 for inactive.
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

from backend.core.config import (
    EXCLUDE_INACTIVE_PLAYERS_FROM_LETTER_RANK,
    LEADERBOARD_INACTIVITY_DAYS,
)
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

    # Join player_name and nationality from players_df (authoritative source).
    player_map = players_df.select("discord_uid", "nationality", "player_name")
    df = df.drop("player_name").join(player_map, on="discord_uid", how="left")

    # Compute win_rate and nonlose_rate as sort columns.
    # games_played > 0 is guaranteed by the filter above.
    df = df.with_columns(
        (pl.col("games_won") / pl.col("games_played")).alias("win_rate"),
        ((pl.col("games_won") + pl.col("games_drawn")) / pl.col("games_played")).alias(
            "nonlose_rate"
        ),
    )

    # Sort by full tiebreaker cascade. nulls_last=True ensures any unexpected
    # null last_played_at values sink to the bottom on the descending pass.
    df = df.sort(
        [
            "mmr",
            "last_played_at",
            "win_rate",
            "nonlose_rate",
            "games_played",
            "player_name",
        ],
        descending=[True, True, True, True, True, False],
        nulls_last=True,
    )

    rows = df.select(
        "discord_uid",
        "player_name",
        "race",
        "nationality",
        "mmr",
        "games_played",
        "games_won",
        "games_lost",
        "games_drawn",
        "last_played_at",
    ).to_dicts()

    # --- Ordinal rank (all entries) ---
    ordinal_ranks: list[int] = []
    prev_key: tuple | None = None
    prev_rank = 0
    for idx, row in enumerate(rows):
        key = _rank_key(row)
        if key != prev_key:
            prev_rank = idx + 1
            prev_key = key
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

    # --- Active ordinal rank (active entries only) ---
    active_ordinal_map: dict[int, int] = {}
    a_prev_key: tuple | None = None
    a_prev_rank = 0
    for pos, idx in enumerate(active_indices):
        key = _rank_key(rows[idx])
        if key != a_prev_key:
            a_prev_rank = pos + 1
            a_prev_key = key
        active_ordinal_map[idx] = a_prev_rank

    # --- Letter rank allocation ---
    if EXCLUDE_INACTIVE_PLAYERS_FROM_LETTER_RANK:
        # Allocate only across active players; inactive get "U".
        rank_indices = active_indices
    else:
        # Allocate across all players regardless of activity.
        rank_indices = list(range(len(rows)))

    allocations = _calculate_allocations(len(rank_indices))

    letter_rank_map: dict[int, str] = {}
    pos = 0
    for rank_letter in _RANK_ORDER:
        count = allocations[rank_letter]
        for _ in range(count):
            if pos < len(rank_indices):
                letter_rank_map[rank_indices[pos]] = rank_letter
                pos += 1

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
                games_won=row["games_won"],
                games_lost=row["games_lost"],
                games_drawn=row["games_drawn"],
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


_MIN_DATETIME: datetime = datetime.min.replace(tzinfo=timezone.utc)


def _rank_key(row: dict) -> tuple:
    """Return the sort key tuple used for rank equality checks.

    Criteria: MMR desc, last_played_at desc, win_rate desc, nonlose_rate desc,
    games_played desc, player_name asc.  Two rows share a rank only when all
    six criteria are identical.
    """
    lp = row["last_played_at"]
    lp_dt = _ensure_utc(lp) if lp is not None else _MIN_DATETIME
    gp: int = row["games_played"]
    win_rate = row["games_won"] / gp
    nonlose_rate = (row["games_won"] + row["games_drawn"]) / gp
    return (row["mmr"], lp_dt, win_rate, nonlose_rate, gp, row["player_name"] or "")
