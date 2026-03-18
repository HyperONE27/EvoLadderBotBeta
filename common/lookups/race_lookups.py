from common.json_types import Race
from common.protocols import StaticDataSource

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_source: StaticDataSource | None = None

# ----------------
# Internal helpers
# ----------------


def _get_source() -> StaticDataSource:
    if _source is None:
        raise RuntimeError(_MODULE_NOT_INITIALIZED)
    return _source


# ----------
# Public API
# ----------


def get_races() -> dict[str, Race]:
    return _get_source().races


def get_race_by_code(code: str) -> Race | None:
    return get_races().get(code)


def get_race_by_name(name: str) -> Race | None:
    return next((race for race in get_races().values() if race["name"] == name), None)


def get_race_by_short_name(short_name: str) -> Race | None:
    return next(
        (race for race in get_races().values() if race["short_name"] == short_name),
        None,
    )


def get_race_by_alias(alias: str) -> Race | None:
    return next(
        (race for race in get_races().values() if alias in race["aliases"]), None
    )


def get_bw_race_codes() -> list[str]:
    """Return race codes where ``is_bw_race`` is True."""
    return [code for code, race in get_races().items() if race["is_bw_race"]]


def get_sc2_race_codes() -> list[str]:
    """Return race codes where ``is_sc2_race`` is True."""
    return [code for code, race in get_races().items() if race["is_sc2_race"]]


# ----------------
# Module lifecycle
# ----------------


def init_race_lookups(source: StaticDataSource) -> None:
    """Initialize the race lookups module."""
    global _source
    _source = source
