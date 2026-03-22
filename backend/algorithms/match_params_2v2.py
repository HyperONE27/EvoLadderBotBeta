"""
Stateless 2v2 match-parameter resolution.

Single entry point: ``resolve_match_params_2v2``

Accepts a ``MatchCandidate2v2`` together with the loaded static data (maps,
cross-table) and returns a ``MatchParams2v2`` containing the chosen map,
server, and in-game channel.

No global state, no singletons, no I/O, no mutation of inputs.

Server selection
----------------
Four players means up to four region codes.  All non-None regions are taken,
all unique ordered pairs (i, j) are looked up in the cross-table, and the
server that appears most often wins.  Ties are broken randomly.

If only one unique region is present the self-pair lookup is used.  If no
regions are available a ``ValueError`` is raised.

Map selection
-------------
Both teams' vetoes are combined (union).  A random map is chosen from the
remaining pool for the ``"2v2"`` game-mode key in maps.json.
"""

from __future__ import annotations

import random
from collections import Counter
from itertools import combinations

from backend.algorithms.match_params import _available_maps, _resolve_server
from backend.core.config import IN_GAME_CHANNEL
from backend.domain_types.ephemeral import MatchCandidate2v2, MatchParams2v2
from common.json_types import CrossTableData, GameModeData


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_server_for_group(
    cross_table: CrossTableData,
    locations: list[str | None],
) -> str:
    """Return the best server for a group of up to four players.

    Raises
    ------
    ValueError
        If no non-None locations are provided.
    """
    regions = [r for r in locations if r is not None]
    if not regions:
        raise ValueError("No location data available for any player in the match.")

    unique = list(dict.fromkeys(regions))  # deduplicate, preserve order

    if len(unique) == 1:
        # Self-pair lookup gives the local server for that region.
        return _resolve_server(cross_table, unique[0], unique[0])

    counts: Counter[str] = Counter()
    for r1, r2 in combinations(unique, 2):
        counts[_resolve_server(cross_table, r1, r2)] += 1

    max_count = max(counts.values())
    winners = [server for server, n in counts.items() if n == max_count]
    return random.choice(winners)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_match_params_2v2(
    candidate: MatchCandidate2v2,
    *,
    maps: dict[str, GameModeData],
    cross_table: CrossTableData,
    season: str,
) -> MatchParams2v2:
    """Choose map, server, and channel for a 2v2 match candidate.

    Parameters
    ----------
    candidate:
        The matched pair produced by ``matchmaker_2v2.run_matchmaking_wave_2v2``.
    maps:
        The full ``maps`` dict loaded from ``data/core/maps.json``.
    cross_table:
        The cross-table loaded from ``data/core/cross_table.json``.
    season:
        The current season key (e.g. ``"season_alpha"``).

    Raises
    ------
    KeyError
        If the ``"2v2"`` game-mode key or the season key is absent from *maps*.
    ValueError
        If no maps remain after applying both teams' vetoes, or if no player
        has location data for server selection.
    """
    combined_vetoes = list(
        set(candidate["team_1_map_vetoes"]) | set(candidate["team_2_map_vetoes"])
    )
    pool = _available_maps(maps, "2v2", season, combined_vetoes, [])
    if not pool:
        raise ValueError(
            f"No maps available after vetoes for "
            f"team_1={candidate['team_1_player_1_discord_uid']} vs "
            f"team_2={candidate['team_2_player_1_discord_uid']}"
        )

    map_name = random.choice(pool)
    server_name = _resolve_server_for_group(
        cross_table,
        [
            candidate["team_1_player_1_location"],
            candidate["team_1_player_2_location"],
            candidate["team_2_player_1_location"],
            candidate["team_2_player_2_location"],
        ],
    )

    return MatchParams2v2(
        map_name=map_name,
        server_name=server_name,
        in_game_channel=IN_GAME_CHANNEL,
    )
