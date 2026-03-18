"""
Recalculate game statistics (played/won/lost/drawn) from the matches_1v1
ground truth rather than relying on incremental counters.

Only matches with a countable result (player_1_win, player_2_win, draw) are
included.  Other outcomes (conflict, abort, abandoned, invalidated, no_report)
are excluded.
"""

import polars as pl


_COUNTABLE_RESULTS = {"player_1_win", "player_2_win", "draw"}


def count_game_stats(
    matches_df: pl.DataFrame, discord_uid: int, race: str
) -> dict[str, int]:
    """Return ``{games_played, games_won, games_lost, games_drawn}`` for
    *discord_uid* playing *race*, derived entirely from *matches_df*."""

    # Player as player_1 with this race
    p1 = matches_df.filter(
        (pl.col("player_1_discord_uid") == discord_uid)
        & (pl.col("player_1_race") == race)
        & pl.col("match_result").is_in(_COUNTABLE_RESULTS)
    )
    # Player as player_2 with this race
    p2 = matches_df.filter(
        (pl.col("player_2_discord_uid") == discord_uid)
        & (pl.col("player_2_race") == race)
        & pl.col("match_result").is_in(_COUNTABLE_RESULTS)
    )

    won = 0
    lost = 0
    drawn = 0

    if not p1.is_empty():
        results = p1["match_result"].to_list()
        won += results.count("player_1_win")
        lost += results.count("player_2_win")
        drawn += results.count("draw")

    if not p2.is_empty():
        results = p2["match_result"].to_list()
        won += results.count("player_2_win")
        lost += results.count("player_1_win")
        drawn += results.count("draw")

    return {
        "games_played": won + lost + drawn,
        "games_won": won,
        "games_lost": lost,
        "games_drawn": drawn,
    }
