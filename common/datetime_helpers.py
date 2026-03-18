"""
Centralised datetime utilities for the EvoLadder codebase.

Canonical representations
-------------------------
- **In-memory:** ``datetime`` objects that are always UTC-aware
  (``tzinfo=timezone.utc``).
- **Serialised:** ISO 8601 strings produced by ``to_iso()``, e.g.
  ``"2026-03-17T01:52:30.102351+00:00"``.

Every public function in this module accepts *either* a ``datetime`` or an
ISO-format string (keyword-only) so callers never need to pre-normalise.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical "now"
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Parsing / normalisation
# ---------------------------------------------------------------------------


def ensure_utc(value: Any) -> datetime | None:
    """Normalise *value* to a UTC-aware ``datetime``, or ``None``.

    Accepts:
    - ``datetime`` (aware → returned as-is; naive → assumed UTC)
    - ``str`` (ISO 8601 variants including ``Z`` and ``+00`` suffixes)
    - ``None`` / falsy → returns ``None``

    Logs a warning on unparseable input rather than raising.
    """
    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    if not isinstance(value, str):
        logger.warning(
            "ensure_utc: unexpected type %s for value %r", type(value).__name__, value
        )
        return None

    try:
        # Normalise common ISO 8601 variants before parsing.
        s = value
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        elif s.endswith("+00"):
            s = s + ":00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError) as exc:
        logger.warning("ensure_utc: failed to parse %r: %s", value, exc)
        return None


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def to_iso(*, dt: datetime | None = None, raw: Any = None) -> str | None:
    """Serialise to the canonical ISO 8601 string, or ``None``.

    Pass **one** of *dt* (an already-normalised datetime) or *raw* (anything
    ``ensure_utc`` can handle).  *raw* is normalised first.
    """
    resolved = _resolve(dt=dt, raw=raw)
    if resolved is None:
        return None
    return resolved.isoformat()


def to_discord_timestamp(
    *, dt: datetime | None = None, raw: Any = None, style: str = "F"
) -> str:
    """Format as a Discord relative timestamp ``<t:UNIX:style>``, or ``"—"``.

    Common styles: ``F`` (full), ``f`` (short), ``R`` (relative), ``D`` (date).
    """
    resolved = _resolve(dt=dt, raw=raw)
    if resolved is None:
        return "—"
    return f"<t:{int(resolved.timestamp())}:{style}>"


def to_display(*, dt: datetime | None = None, raw: Any = None) -> str:
    """Human-readable UTC string with a Discord timestamp on the next line.

    Example::

        17 Mar 2026, 01:52:30 UTC
        (<t:1773976350>)

    Returns ``"—"`` for ``None`` / unparseable input.
    """
    resolved = _resolve(dt=dt, raw=raw)
    if resolved is None:
        return "—"
    human = resolved.strftime("%d %b %Y, %H:%M:%S UTC")
    unix = int(resolved.timestamp())
    return f"{human}\n(<t:{unix}>)"


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _resolve(*, dt: datetime | None = None, raw: Any = None) -> datetime | None:
    """Return a UTC-aware datetime from whichever keyword arg was supplied."""
    if dt is not None:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    if raw is not None:
        return ensure_utc(raw)
    return None
