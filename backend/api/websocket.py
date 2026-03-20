"""
WebSocket connection manager for pushing real-time events to the bot process.

Usage
-----
The bot connects to ``/ws`` and receives JSON messages of the form::

    {"event": "<event_type>", "data": { ... }}

Event types: ``match_found``, ``both_confirmed``, ``match_aborted``,
``match_abandoned``, ``match_completed``, ``match_conflict``,
``leaderboard_updated``, ``queue_join_activity``.

``queue_join_activity`` data includes ``game_mode``, ``notify_discord_uids``,
and ``footers`` (subscriber uid string to DM footer text).
"""

import json
from datetime import datetime

import structlog
from fastapi import WebSocket

from common.datetime_helpers import to_iso

logger = structlog.get_logger(__name__)


def _json_default(obj: object) -> str:
    if isinstance(obj, datetime):
        return to_iso(dt=obj) or ""
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class ConnectionManager:
    """Manages a set of active WebSocket connections from bot instances."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("WebSocket client connected", total=len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections = [c for c in self._connections if c is not ws]
        logger.info("WebSocket client disconnected", total=len(self._connections))

    async def broadcast(self, event: str, data: dict) -> None:
        """Send an event to every connected client."""
        payload = json.dumps({"event": event, "data": data}, default=_json_default)
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)
