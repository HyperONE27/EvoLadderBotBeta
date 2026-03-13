from common.json_types import Emote
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


def _get_emotes() -> dict[str, Emote]:
    return _get_source().emotes


# ----------
# Public API
# ----------


def get_emote_by_name(name: str) -> Emote | None:
    return _get_emotes().get(name)


def get_emote_by_short_name(short_name: str) -> Emote | None:
    return next(
        (
            emote
            for emote in _get_emotes().values()
            if emote["short_name"] == short_name
        ),
        None,
    )


def get_emote_by_markdown(markdown: str) -> Emote | None:
    return next(
        (emote for emote in _get_emotes().values() if emote["markdown"] == markdown),
        None,
    )


# ----------------
# Module lifecycle
# ----------------


def init_emote_lookups(source: StaticDataSource) -> None:
    """Initialize the emote lookups module."""
    global _source
    _source = source
