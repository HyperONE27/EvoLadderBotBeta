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


def _get_races() -> dict[str, Race]:
    return _get_source().races


# ----------
# Public API
# ----------


def get_race_by_code(code: str) -> Race | None:
    return _get_races().get(code)


def get_race_by_name(name: str) -> Race | None:
    return next((race for race in _get_races().values() if race["name"] == name), None)


def get_race_by_short_name(short_name: str) -> Race | None:
    return next(
        (race for race in _get_races().values() if race["short_name"] == short_name),
        None,
    )


def get_race_by_alias(alias: str) -> Race | None:
    return next(
        (race for race in _get_races().values() if alias in race["aliases"]), None
    )


# ----------------
# Module lifecycle
# ----------------


def init_race_lookups(source: StaticDataSource) -> None:
    """Initialize the race lookups module."""
    global _source
    _source = source
