"""Leaderboard computation — pure, stateless, no I/O.

Takes the in-memory ``mmrs_1v1_df`` and ``players_df`` Polars DataFrames and
returns a fully ranked ``list[LeaderboardEntry1v1]``.
"""

import math

import polars as pl

from backend.domain_types.ephemeral import LeaderboardEntry1v1

# Percentile-based tier splits (cumulative upper bounds).
# S: top 1%, A: next 7%, B–E: 21% each, F: bottom 8%.
_TIER_SPLITS: list[tuple[str, float]] = [
    ("S", 0.01),
    ("A", 0.08),
    ("B", 0.29),
    ("C", 0.50),
    ("D", 0.71),
    ("E", 0.92),
    ("F", 1.00),
]


def build_leaderboard_1v1(
    mmrs_1v1_df: pl.DataFrame,
    players_df: pl.DataFrame,
) -> list[LeaderboardEntry1v1]:
    """Compute the 1v1 leaderboard from the current DataFrames.

    1. Filter out rows with ``games_played == 0``.
    2. Join ``nationality`` from *players_df*.
    3. Sort by MMR descending, then ``last_played_at`` descending.
    4. Assign dense ordinal ranks (tied MMR → same rank).
    5. Assign letter ranks using percentile-based tier splits.
    """
    df = mmrs_1v1_df.filter(pl.col("games_played") > 0)

    if df.is_empty():
        return []

    # Join nationality from players_df (left join on discord_uid).
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

    total = len(rows)
    tier_boundaries = _compute_tier_boundaries(total)

    entries: list[LeaderboardEntry1v1] = []
    prev_mmr: int | None = None
    prev_rank = 0

    for idx, row in enumerate(rows):
        mmr_val: int = row["mmr"]

        # Dense ranking: same MMR → same ordinal rank.
        if mmr_val != prev_mmr:
            prev_rank = idx + 1
            prev_mmr = mmr_val

        letter_rank = _letter_rank_for_position(idx, tier_boundaries)

        entries.append(
            LeaderboardEntry1v1(
                discord_uid=row["discord_uid"],
                player_name=row["player_name"],
                ordinal_rank=prev_rank,
                letter_rank=letter_rank,
                race=row["race"],
                nationality=row["nationality"] or "",
                mmr=mmr_val,
                games_played=row["games_played"],
                last_played_at=row["last_played_at"],
            )
        )

    return entries


def _compute_tier_boundaries(total: int) -> list[tuple[str, int]]:
    """Return ``(letter, last_index)`` pairs for each tier.

    Uses ceiling so that the top tier always contains at least one player.
    """
    boundaries: list[tuple[str, int]] = []
    for letter, cumulative_pct in _TIER_SPLITS:
        boundary_idx = math.ceil(total * cumulative_pct) - 1
        boundaries.append((letter, boundary_idx))
    return boundaries


def _letter_rank_for_position(idx: int, tier_boundaries: list[tuple[str, int]]) -> str:
    """Return the letter rank for the player at *idx* (0-based)."""
    for letter, boundary_idx in tier_boundaries:
        if idx <= boundary_idx:
            return letter
    return "F"
