"""Invariant tests for game statistics (backend.algorithms.game_stats).

Key invariants:
- games_played == games_won + games_lost + games_drawn
- Only countable results are counted
- Player position (p1 vs p2, t1 vs t2) is handled correctly
- Leader/member order doesn't matter for 2v2
"""

import polars as pl

from backend.algorithms.game_stats import (
    count_game_stats,
    count_game_stats_2v2,
)


# ---------------------------------------------------------------------------
# 1v1 fixtures
# ---------------------------------------------------------------------------


def _matches_1v1_df(rows: list[dict]) -> pl.DataFrame:
    """Build a minimal matches_1v1 DataFrame from dicts."""
    if not rows:
        return pl.DataFrame(
            schema={
                "player_1_discord_uid": pl.Int64,
                "player_2_discord_uid": pl.Int64,
                "player_1_race": pl.Utf8,
                "player_2_race": pl.Utf8,
                "match_result": pl.Utf8,
            }
        )
    return pl.DataFrame(rows)


def _matches_2v2_df(rows: list[dict]) -> pl.DataFrame:
    """Build a minimal matches_2v2 DataFrame from dicts."""
    if not rows:
        return pl.DataFrame(
            schema={
                "team_1_player_1_discord_uid": pl.Int64,
                "team_1_player_2_discord_uid": pl.Int64,
                "team_2_player_1_discord_uid": pl.Int64,
                "team_2_player_2_discord_uid": pl.Int64,
                "match_result": pl.Utf8,
            }
        )
    return pl.DataFrame(rows)


# ---------------------------------------------------------------------------
# 1v1: arithmetic invariant — played == won + lost + drawn
# ---------------------------------------------------------------------------


class TestGameStats1v1:
    def test_arithmetic_invariant(self) -> None:
        df = _matches_1v1_df(
            [
                {
                    "player_1_discord_uid": 1,
                    "player_2_discord_uid": 2,
                    "player_1_race": "bw_terran",
                    "player_2_race": "sc2_zerg",
                    "match_result": "player_1_win",
                },
                {
                    "player_1_discord_uid": 1,
                    "player_2_discord_uid": 3,
                    "player_1_race": "bw_terran",
                    "player_2_race": "sc2_protoss",
                    "match_result": "player_2_win",
                },
                {
                    "player_1_discord_uid": 4,
                    "player_2_discord_uid": 1,
                    "player_1_race": "sc2_terran",
                    "player_2_race": "bw_terran",
                    "match_result": "draw",
                },
                {
                    "player_1_discord_uid": 1,
                    "player_2_discord_uid": 5,
                    "player_1_race": "bw_terran",
                    "player_2_race": "sc2_zerg",
                    "match_result": "player_1_win",
                },
            ]
        )
        stats = count_game_stats(df, 1, "bw_terran")
        assert (
            stats["games_played"]
            == stats["games_won"] + stats["games_lost"] + stats["games_drawn"]
        )

    def test_empty_dataframe(self) -> None:
        df = _matches_1v1_df([])
        stats = count_game_stats(df, 1, "bw_terran")
        assert stats == {
            "games_played": 0,
            "games_won": 0,
            "games_lost": 0,
            "games_drawn": 0,
        }

    def test_non_countable_excluded(self) -> None:
        """Matches with non-countable results are not counted."""
        df = _matches_1v1_df(
            [
                {
                    "player_1_discord_uid": 1,
                    "player_2_discord_uid": 2,
                    "player_1_race": "bw_terran",
                    "player_2_race": "sc2_zerg",
                    "match_result": "player_1_win",
                },
                {
                    "player_1_discord_uid": 1,
                    "player_2_discord_uid": 3,
                    "player_1_race": "bw_terran",
                    "player_2_race": "sc2_zerg",
                    "match_result": "conflict",
                },
                {
                    "player_1_discord_uid": 1,
                    "player_2_discord_uid": 4,
                    "player_1_race": "bw_terran",
                    "player_2_race": "sc2_zerg",
                    "match_result": "abort",
                },
                {
                    "player_1_discord_uid": 1,
                    "player_2_discord_uid": 5,
                    "player_1_race": "bw_terran",
                    "player_2_race": "sc2_zerg",
                    "match_result": "abandoned",
                },
                {
                    "player_1_discord_uid": 1,
                    "player_2_discord_uid": 6,
                    "player_1_race": "bw_terran",
                    "player_2_race": "sc2_zerg",
                    "match_result": "invalidated",
                },
                {
                    "player_1_discord_uid": 1,
                    "player_2_discord_uid": 7,
                    "player_1_race": "bw_terran",
                    "player_2_race": "sc2_zerg",
                    "match_result": "no_report",
                },
            ]
        )
        stats = count_game_stats(df, 1, "bw_terran")
        assert stats["games_played"] == 1
        assert stats["games_won"] == 1

    def test_win_as_p1_and_p2(self) -> None:
        """A win is counted correctly regardless of which slot the player is in."""
        df = _matches_1v1_df(
            [
                {
                    "player_1_discord_uid": 1,
                    "player_2_discord_uid": 2,
                    "player_1_race": "bw_terran",
                    "player_2_race": "sc2_zerg",
                    "match_result": "player_1_win",
                },
                {
                    "player_1_discord_uid": 3,
                    "player_2_discord_uid": 1,
                    "player_1_race": "sc2_zerg",
                    "player_2_race": "bw_terran",
                    "match_result": "player_2_win",
                },
            ]
        )
        stats = count_game_stats(df, 1, "bw_terran")
        assert stats["games_won"] == 2
        assert stats["games_lost"] == 0

    def test_race_filter(self) -> None:
        """Stats for one race don't include matches played as another."""
        df = _matches_1v1_df(
            [
                {
                    "player_1_discord_uid": 1,
                    "player_2_discord_uid": 2,
                    "player_1_race": "bw_terran",
                    "player_2_race": "sc2_zerg",
                    "match_result": "player_1_win",
                },
                {
                    "player_1_discord_uid": 1,
                    "player_2_discord_uid": 3,
                    "player_1_race": "bw_zerg",
                    "player_2_race": "sc2_zerg",
                    "match_result": "player_1_win",
                },
            ]
        )
        stats_terran = count_game_stats(df, 1, "bw_terran")
        stats_zerg = count_game_stats(df, 1, "bw_zerg")
        assert stats_terran["games_played"] == 1
        assert stats_zerg["games_played"] == 1

    def test_loss_as_p1(self) -> None:
        df = _matches_1v1_df(
            [
                {
                    "player_1_discord_uid": 1,
                    "player_2_discord_uid": 2,
                    "player_1_race": "bw_terran",
                    "player_2_race": "sc2_zerg",
                    "match_result": "player_2_win",
                },
            ]
        )
        stats = count_game_stats(df, 1, "bw_terran")
        assert stats["games_lost"] == 1
        assert stats["games_won"] == 0


# ---------------------------------------------------------------------------
# 2v2: same invariants, different schema
# ---------------------------------------------------------------------------


class TestGameStats2v2:
    def test_arithmetic_invariant(self) -> None:
        df = _matches_2v2_df(
            [
                {
                    "team_1_player_1_discord_uid": 1,
                    "team_1_player_2_discord_uid": 2,
                    "team_2_player_1_discord_uid": 3,
                    "team_2_player_2_discord_uid": 4,
                    "match_result": "team_1_win",
                },
                {
                    "team_1_player_1_discord_uid": 1,
                    "team_1_player_2_discord_uid": 2,
                    "team_2_player_1_discord_uid": 5,
                    "team_2_player_2_discord_uid": 6,
                    "match_result": "team_2_win",
                },
                {
                    "team_1_player_1_discord_uid": 7,
                    "team_1_player_2_discord_uid": 8,
                    "team_2_player_1_discord_uid": 1,
                    "team_2_player_2_discord_uid": 2,
                    "match_result": "draw",
                },
            ]
        )
        stats = count_game_stats_2v2(df, 1, 2)
        assert (
            stats["games_played"]
            == stats["games_won"] + stats["games_lost"] + stats["games_drawn"]
        )
        assert stats["games_played"] == 3

    def test_empty_dataframe(self) -> None:
        df = _matches_2v2_df([])
        stats = count_game_stats_2v2(df, 1, 2)
        assert stats == {
            "games_played": 0,
            "games_won": 0,
            "games_lost": 0,
            "games_drawn": 0,
        }

    def test_order_independent(self) -> None:
        """(uid_a, uid_b) and (uid_b, uid_a) produce the same result."""
        df = _matches_2v2_df(
            [
                {
                    "team_1_player_1_discord_uid": 1,
                    "team_1_player_2_discord_uid": 2,
                    "team_2_player_1_discord_uid": 3,
                    "team_2_player_2_discord_uid": 4,
                    "match_result": "team_1_win",
                },
                {
                    "team_1_player_1_discord_uid": 2,
                    "team_1_player_2_discord_uid": 1,
                    "team_2_player_1_discord_uid": 5,
                    "team_2_player_2_discord_uid": 6,
                    "match_result": "team_2_win",
                },
            ]
        )
        stats_12 = count_game_stats_2v2(df, 1, 2)
        stats_21 = count_game_stats_2v2(df, 2, 1)
        assert stats_12 == stats_21

    def test_non_countable_excluded(self) -> None:
        df = _matches_2v2_df(
            [
                {
                    "team_1_player_1_discord_uid": 1,
                    "team_1_player_2_discord_uid": 2,
                    "team_2_player_1_discord_uid": 3,
                    "team_2_player_2_discord_uid": 4,
                    "match_result": "team_1_win",
                },
                {
                    "team_1_player_1_discord_uid": 1,
                    "team_1_player_2_discord_uid": 2,
                    "team_2_player_1_discord_uid": 5,
                    "team_2_player_2_discord_uid": 6,
                    "match_result": "conflict",
                },
                {
                    "team_1_player_1_discord_uid": 1,
                    "team_1_player_2_discord_uid": 2,
                    "team_2_player_1_discord_uid": 7,
                    "team_2_player_2_discord_uid": 8,
                    "match_result": "abort",
                },
            ]
        )
        stats = count_game_stats_2v2(df, 1, 2)
        assert stats["games_played"] == 1

    def test_team_position_correct(self) -> None:
        """Win as team_1 and win as team_2 both count as wins."""
        df = _matches_2v2_df(
            [
                {
                    "team_1_player_1_discord_uid": 1,
                    "team_1_player_2_discord_uid": 2,
                    "team_2_player_1_discord_uid": 3,
                    "team_2_player_2_discord_uid": 4,
                    "match_result": "team_1_win",
                },
                {
                    "team_1_player_1_discord_uid": 5,
                    "team_1_player_2_discord_uid": 6,
                    "team_2_player_1_discord_uid": 1,
                    "team_2_player_2_discord_uid": 2,
                    "match_result": "team_2_win",
                },
            ]
        )
        stats = count_game_stats_2v2(df, 1, 2)
        assert stats["games_won"] == 2
        assert stats["games_lost"] == 0
