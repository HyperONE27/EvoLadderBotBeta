from common.json_types import Country
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


def get_countries() -> dict[str, Country]:
    return _get_source().countries


def get_common_countries() -> dict[str, Country]:
    """Get only common countries."""
    return {
        code: country for code, country in get_countries().items() if country["common"]
    }


def get_country_by_code(code: str) -> Country | None:
    return get_countries().get(code)


def get_country_by_name(name: str) -> Country | None:
    return next(
        (country for country in get_countries().values() if country["name"] == name),
        None,
    )


def search_countries_by_partial_code(partial_code: str) -> dict[str, Country]:
    """Search countries by partial code."""
    return {
        code: country
        for code, country in get_countries().items()
        if partial_code.lower() in code.lower()
    }


def search_countries_by_partial_name(partial_name: str) -> dict[str, Country]:
    """Search countries by partial name."""
    return {
        code: country
        for code, country in get_countries().items()
        if partial_name.lower() in country["name"].lower()
    }


# ----------------
# Module lifecycle
# ----------------


def init_country_lookups(source: StaticDataSource) -> None:
    """Initialize the country lookups module."""
    global _source
    _source = source
