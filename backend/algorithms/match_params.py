"""
Stateless match-parameter resolution.

Single entry point: ``resolve_match_params``

Accepts a ``MatchCandidate1v1`` together with both players' geographic-region
codes and the loaded static data (maps, cross-table) and returns a
``MatchParams1v1`` containing the chosen map, server, and in-game channel.

No global state, no singletons, no I/O, no mutation of inputs.
"""

import random

from backend.core.config import IN_GAME_CHANNEL
from backend.domain_types.ephemeral import MatchCandidate1v1, MatchParams1v1
from common.json_types import CrossTableData, GameModeData


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _available_maps(
    maps: dict[str, GameModeData],
    game_mode: str,
    season: str,
    p1_vetoes: list[str],
    p2_vetoes: list[str],
) -> list[str]:
    """Return full map names that neither player has vetoed.

    Raises
    ------
    KeyError
        If *game_mode* is not present in *maps* (data error).
    """
    if game_mode not in maps:
        raise KeyError(
            f"Game mode {game_mode!r} not found in maps data. "
            f"Known game modes: {list(maps.keys())}"
        )
    season_data = maps[game_mode].get(season)
    if season_data is None:
        raise KeyError(f"Season {season!r} not found under game mode {game_mode!r}.")
    vetoed = set(p1_vetoes) | set(p2_vetoes)
    # Return the long ``name`` for each map so the value that flows into
    # ``matches_*.map_name`` matches the sc2reader long name stored in
    # ``replays_*.map_name`` at verification time. Vetoes are compared in the
    # same namespace (long names) — see MapVetoSelect.
    result: list[str] = []
    for short_name, map_data in season_data.items():
        if not short_name.strip():
            continue
        long_name = map_data.get("name") or short_name
        if long_name in vetoed:
            continue
        result.append(long_name)
    return result


def _resolve_server(
    cross_table: CrossTableData,
    region_1: str,
    region_2: str,
) -> str:
    """Look up the recommended game-server name for a region pair."""
    order = cross_table["region_order"]
    if region_1 not in order or region_2 not in order:
        raise ValueError(
            f"Unknown region(s): {region_1!r}, {region_2!r}. Known regions: {order}"
        )

    # Canonical ordering so the mapping table is symmetric.
    if order.index(region_1) > order.index(region_2):
        region_1, region_2 = region_2, region_1

    return cross_table["mappings"][region_1][region_2]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_match_params(
    candidate: MatchCandidate1v1,
    *,
    player_1_location: str,
    player_2_location: str,
    maps: dict[str, GameModeData],
    cross_table: CrossTableData,
    season: str,
) -> MatchParams1v1:
    """Choose map, server, and channel for a single match candidate.

    Parameters
    ----------
    candidate:
        The matched pair produced by ``matchmaker.run_matchmaking_wave``.
    player_1_location:
        Geographic-region code for player 1 (e.g. ``"NA"``).
    player_2_location:
        Geographic-region code for player 2.
    maps:
        The full ``maps`` dict loaded from ``data/core/maps.json``.
    cross_table:
        The cross-table loaded from ``data/core/cross_table.json``.
    season:
        The current season key (e.g. ``"season_alpha"``).

    Raises
    ------
    ValueError
        If no maps remain after applying both players' vetoes.
    """
    pool = _available_maps(
        maps,
        "1v1",
        season,
        candidate["player_1_map_vetoes"],
        candidate["player_2_map_vetoes"],
    )
    if not pool:
        raise ValueError(
            f"No maps available after vetoes for "
            f"{candidate['player_1_discord_uid']} vs "
            f"{candidate['player_2_discord_uid']}"
        )

    map_name = random.choice(pool)
    server_name = _resolve_server(cross_table, player_1_location, player_2_location)

    return MatchParams1v1(
        map_name=map_name,
        server_name=server_name,
        in_game_channel=IN_GAME_CHANNEL,
    )
