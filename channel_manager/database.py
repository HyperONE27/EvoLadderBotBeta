"""Supabase wrapper for the channel_manager's channels table."""

import structlog
from supabase import create_client, Client

from channel_manager.config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

logger = structlog.get_logger(__name__)


class ChannelDatabase:
    def __init__(self) -> None:
        self._client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    def insert_channel(
        self,
        match_id: int,
        match_mode: str,
        channel_id: int,
        message_id: int,
        message_url: str,
    ) -> dict:
        """Insert a new channel row and return it."""
        result = (
            self._client.table("channels")
            .insert(
                {
                    "match_id": match_id,
                    "match_mode": match_mode,
                    "channel_id": channel_id,
                    "message_id": message_id,
                    "message_url": message_url,
                }
            )
            .execute()
        )
        return result.data[0]

    def get_channel_by_match_id(self, match_id: int) -> dict | None:
        """Return the channel row for a match, or None if not found."""
        result = (
            self._client.table("channels")
            .select("*")
            .eq("match_id", match_id)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def mark_deleted(self, channel_id: int) -> None:
        """Stamp deleted_at on the channel row."""
        from datetime import datetime, timezone

        self._client.table("channels").update(
            {"deleted_at": datetime.now(timezone.utc).isoformat()}
        ).eq("channel_id", channel_id).execute()
