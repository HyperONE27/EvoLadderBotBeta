"""
Async Discord REST client for channel lifecycle management.

Uses httpx directly against the Discord API v10; no gateway connection needed.
"""

import structlog
import httpx

from channel_manager.config import DISCORD_BOT_TOKEN

logger = structlog.get_logger(__name__)

_DISCORD_API_BASE = "https://discord.com/api/v10"

# Permission bitfields
_VIEW_CHANNEL = 1 << 10  # 1024
_SEND_MESSAGES = 1 << 11  # 2048
_READ_MESSAGE_HISTORY = 1 << 14  # 16384
_MEMBER_ALLOW = _VIEW_CHANNEL | _SEND_MESSAGES | _READ_MESSAGE_HISTORY


class DiscordClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            base_url=_DISCORD_API_BASE,
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"},
            timeout=10.0,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def create_channel(
        self,
        guild_id: int,
        category_id: int,
        name: str,
        allow_member_ids: list[int],
        allow_role_ids: list[int],
    ) -> int:
        """Create a private text channel. Returns the new channel's snowflake ID."""
        overwrites = [
            # Deny @everyone (role ID == guild ID)
            {"id": str(guild_id), "type": 0, "allow": "0", "deny": str(_VIEW_CHANNEL)},
        ]
        for role_id in allow_role_ids:
            overwrites.append(
                {
                    "id": str(role_id),
                    "type": 0,
                    "allow": str(_MEMBER_ALLOW),
                    "deny": "0",
                }
            )
        for member_id in allow_member_ids:
            overwrites.append(
                {
                    "id": str(member_id),
                    "type": 1,
                    "allow": str(_MEMBER_ALLOW),
                    "deny": "0",
                }
            )

        resp = await self._http.post(
            f"/guilds/{guild_id}/channels",
            json={
                "name": name,
                "type": 0,  # GUILD_TEXT
                "parent_id": str(category_id),
                "permission_overwrites": overwrites,
            },
        )
        resp.raise_for_status()
        return int(resp.json()["id"])

    async def send_message(
        self,
        channel_id: int,
        content: str,
    ) -> int:
        """Send a text message to a channel. Returns the message snowflake ID."""
        resp = await self._http.post(
            f"/channels/{channel_id}/messages",
            json={"content": content},
        )
        resp.raise_for_status()
        return int(resp.json()["id"])

    async def delete_channel(self, channel_id: int) -> None:
        """Delete a guild channel."""
        resp = await self._http.delete(f"/channels/{channel_id}")
        resp.raise_for_status()
