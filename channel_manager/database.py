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

    def get_channel_by_match_id(self, match_id: int, match_mode: str) -> dict | None:
        """Return the channel row for a match, or None if not found."""
        result = (
            self._client.table("channels")
            .select("*")
            .eq("match_id", match_id)
            .eq("match_mode", match_mode)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_channel_by_channel_id(self, channel_id: int) -> dict | None:
        """Return the active channel row for a Discord channel snowflake, or None."""
        result = (
            self._client.table("channels")
            .select("*")
            .eq("channel_id", channel_id)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def append_message(
        self,
        channel_id: int,
        discord_uid: int,
        content: str,
        ts: str,
    ) -> None:
        """Atomically append one message entry to the channel's messages log."""
        self._client.rpc(
            "append_channel_message",
            {
                "p_channel_id": channel_id,
                "p_message": {
                    "type": "message",
                    "ts": ts,
                    "discord_uid": discord_uid,
                    "content": content,
                },
            },
        ).execute()

    def append_edit(
        self,
        channel_id: int,
        discord_uid: int,
        original_content: str,
        new_content: str,
        ts: str,
    ) -> None:
        """Atomically append one edit entry to the channel's messages log."""
        self._client.rpc(
            "append_channel_message",
            {
                "p_channel_id": channel_id,
                "p_message": {
                    "type": "edit",
                    "ts": ts,
                    "discord_uid": discord_uid,
                    "original_content": original_content,
                    "new_content": new_content,
                },
            },
        ).execute()

    def mark_deleted(self, channel_id: int) -> None:
        """Stamp deleted_at on the channel row."""
        from datetime import datetime, timezone

        self._client.table("channels").update(
            {"deleted_at": datetime.now(timezone.utc).isoformat()}
        ).eq("channel_id", channel_id).execute()
