from common.json_types import Mod
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


def _get_mods() -> dict[str, Mod]:
    return _get_source().mods


# ----------
# Public API
# ----------


def get_mod_by_code(code: str) -> Mod | None:
    return _get_mods().get(code)


def get_mod_by_name(name: str) -> Mod | None:
    return next((mod for mod in _get_mods().values() if mod["name"] == name), None)


def get_mod_by_short_name(short_name: str) -> Mod | None:
    return next(
        (mod for mod in _get_mods().values() if mod["short_name"] == short_name), None
    )


def get_mod_by_link(link: str) -> Mod | None:
    return next(
        (
            mod
            for mod in _get_mods().values()
            if link == mod["am_link"]
            or link == mod["eu_link"]
            or link == mod["as_link"]
        ),
        None,
    )


# ----------------
# Module lifecycle
# ----------------


def init_mod_lookups(source: StaticDataSource) -> None:
    """Initialize the mod lookups module."""
    global _source
    _source = source
