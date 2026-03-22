"""
Recalculate game statistics (played/won/lost/drawn) from the matches_1v1
ground truth rather than relying on incremental counters.

Only matches with a countable result (player_1_win, player_2_win, draw) are
included.  Other outcomes (conflict, abort, abandoned, invalidated, no_report)
are excluded.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl

from common.datetime_helpers import ensure_utc, utc_now

COUNTABLE_MATCH_RESULTS: frozenset[str] = frozenset(
    {"player_1_win", "player_2_win", "draw"}
)

COUNTABLE_MATCH_RESULTS_2V2: frozenset[str] = frozenset(
    {"team_1_win", "team_2_win", "draw"}
)


def count_game_stats(
    matches_df: pl.DataFrame, discord_uid: int, race: str
) -> dict[str, int]:
    """Return ``{games_played, games_won, games_lost, games_drawn}`` for
    *discord_uid* playing *race*, derived entirely from *matches_df*."""

    # Player as player_1 with this race
    p1 = matches_df.filter(
        (pl.col("player_1_discord_uid") == discord_uid)
        & (pl.col("player_1_race") == race)
        & pl.col("match_result").is_in(COUNTABLE_MATCH_RESULTS)
    )
    # Player as player_2 with this race
    p2 = matches_df.filter(
        (pl.col("player_2_discord_uid") == discord_uid)
        & (pl.col("player_2_race") == race)
        & pl.col("match_result").is_in(COUNTABLE_MATCH_RESULTS)
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


def count_game_stats_2v2(
    matches_df: pl.DataFrame, p1_discord_uid: int, p2_discord_uid: int
) -> dict[str, int]:
    """Return ``{games_played, games_won, games_lost, games_drawn}`` for the
    pair ``(p1_discord_uid, p2_discord_uid)`` derived from *matches_df*.

    The pair may appear as team_1 or team_2 in any order (leader / member).
    """
    uid_a, uid_b = p1_discord_uid, p2_discord_uid

    def _as_team(col_p1: str, col_p2: str) -> pl.Expr:
        return ((pl.col(col_p1) == uid_a) & (pl.col(col_p2) == uid_b)) | (
            (pl.col(col_p1) == uid_b) & (pl.col(col_p2) == uid_a)
        )

    as_t1 = matches_df.filter(
        _as_team("team_1_player_1_discord_uid", "team_1_player_2_discord_uid")
        & pl.col("match_result").is_in(COUNTABLE_MATCH_RESULTS_2V2)
    )
    as_t2 = matches_df.filter(
        _as_team("team_2_player_1_discord_uid", "team_2_player_2_discord_uid")
        & pl.col("match_result").is_in(COUNTABLE_MATCH_RESULTS_2V2)
    )

    won = 0
    lost = 0
    drawn = 0

    if not as_t1.is_empty():
        results = as_t1["match_result"].to_list()
        won += results.count("team_1_win")
        lost += results.count("team_2_win")
        drawn += results.count("draw")

    if not as_t2.is_empty():
        results = as_t2["match_result"].to_list()
        won += results.count("team_2_win")
        lost += results.count("team_1_win")
        drawn += results.count("draw")

    return {
        "games_played": won + lost + drawn,
        "games_won": won,
        "games_lost": lost,
        "games_drawn": drawn,
    }


def count_game_stats_in_completed_window(
    matches_df: pl.DataFrame,
    discord_uid: int,
    race: str,
    since: datetime,
    until: datetime | None = None,
) -> dict[str, int]:
    """Like ``count_game_stats`` but only matches with ``completed_at`` in
    ``[since, until]`` (UTC-aware *since* / *until*). Countable outcomes only."""

    if until is None:
        until = utc_now()
    since_utc = ensure_utc(since)
    until_utc = ensure_utc(until)
    if since_utc is None or until_utc is None:
        return {
            "games_played": 0,
            "games_won": 0,
            "games_lost": 0,
            "games_drawn": 0,
        }

    windowed = matches_df.filter(
        pl.col("match_result").is_in(list(COUNTABLE_MATCH_RESULTS))
        & pl.col("completed_at").is_not_null()
        & (pl.col("completed_at") >= since_utc)
        & (pl.col("completed_at") <= until_utc)
    )
    return count_game_stats(windowed, discord_uid, race)
