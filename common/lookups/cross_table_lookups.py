from common.protocols import StaticDataSource

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

# Sentinel value used in the scoring algorithm to represent null (unreachable) pings.
PING_INF: int = 9999

_source: StaticDataSource | None = None

# ----------------
# Internal helpers
# ----------------


def _get_source() -> StaticDataSource:
    if _source is None:
        raise RuntimeError(_MODULE_NOT_INITIALIZED)
    return _source


def _get_region_order() -> list[str]:
    return _get_source().cross_table["region_order"]


def _get_mappings() -> dict[str, dict[str, str]]:
    return _get_source().cross_table["mappings"]


def _get_pings() -> dict[str, dict[str, list[int] | None]]:
    return _get_source().cross_table["pings"]


def _sort_region_pair(region_1: str, region_2: str) -> tuple[str, str]:
    region_order = _get_region_order()
    if region_1 not in region_order or region_2 not in region_order:
        raise ValueError(
            f"Region {region_1!r} or {region_2!r} not found in region_order"
        )
    if region_order.index(region_1) <= region_order.index(region_2):
        return region_1, region_2
    return region_2, region_1


def _ping_to_scalar(ping: list[int] | None) -> int:
    """Collapse a [min, max] ping range to its upper bound, or PING_INF if null."""
    return ping[1] if ping is not None else PING_INF


# ----------
# Public API
# ----------


def get_game_server_from_region_pair(region_1: str, region_2: str) -> str:
    """Return the recommended server for a 1v1 region pair."""
    region_1, region_2 = _sort_region_pair(region_1, region_2)
    return _get_mappings()[region_1][region_2]


def get_ping_range(region: str, server: str) -> list[int] | None:
    """Return the [min_ms, max_ms] ping estimate for a region→server pair, or None if unreachable."""
    pings = _get_pings()
    if region not in pings:
        raise ValueError(f"Region {region!r} not found in ping table")
    if server not in pings[region]:
        raise ValueError(
            f"Server {server!r} not found in ping table for region {region!r}"
        )
    return pings[region][server]


def get_ping_scalar(region: str, server: str) -> int:
    """Return the worst-case ping (upper bound) for a region→server pair.

    Returns PING_INF for null entries so callers can use this in arithmetic
    without special-casing unreachable pairs.
    """
    return _ping_to_scalar(get_ping_range(region, server))


def get_best_server_for_regions(regions: list[str]) -> str:
    """Return the server with the lowest total worst-case ping across all regions.

    Suitable for 1v1 (2 regions) or any N-player same-team scenario where
    fairness between sides is not a concern — pure minimisation of total ping.
    """
    pings = _get_pings()
    servers = next(iter(pings.values())).keys()
    return min(
        servers,
        key=lambda s: sum(get_ping_scalar(r, s) for r in regions),
    )


def get_best_server_for_teams(
    team_1_regions: list[str],
    team_2_regions: list[str],
) -> str:
    """Return the best server for a 2v2 (or any 2-team) match.

    Scoring per candidate server S:

        team1_worst = mean worst-case ping across team 1 players
        team2_worst = mean worst-case ping across team 2 players
        score       = (team1_worst + team2_worst) / 2
                      + |team1_worst - team2_worst|

    The first term minimises overall latency; the second penalises imbalance
    between the two teams. A server with any null entry scores ≥ PING_INF / 2
    and is only chosen when all alternatives are equally poor.
    """
    pings = _get_pings()
    servers = list(next(iter(pings.values())).keys())

    best_server = servers[0]
    best_score = float("inf")

    for server in servers:
        t1 = [get_ping_scalar(r, server) for r in team_1_regions]
        t2 = [get_ping_scalar(r, server) for r in team_2_regions]
        t1_avg = sum(t1) / len(t1)
        t2_avg = sum(t2) / len(t2)
        score = (t1_avg + t2_avg) / 2 + abs(t1_avg - t2_avg)
        if score < best_score:
            best_score = score
            best_server = server

    return best_server


# ----------------
# Module lifecycle
# ----------------


def init_cross_table_lookups(source: StaticDataSource) -> None:
    """Initialize the cross table lookups module."""
    global _source
    _source = source
