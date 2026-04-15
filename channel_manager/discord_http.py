"""
Async Discord REST client for channel lifecycle management.

Uses httpx directly against the Discord API v10; no gateway connection needed.
"""

import asyncio
from typing import Any

import structlog
import httpx

from channel_manager.config import DISCORD_BOT_TOKEN

logger = structlog.get_logger(__name__)

_DISCORD_API_BASE = "https://discord.com/api/v10"

# Permission bitfields
_VIEW_CHANNEL = 1 << 10  # 1024
_SEND_MESSAGES = 1 << 11  # 2048
_CREATE_PUBLIC_THREADS = 1 << 35
_CREATE_PRIVATE_THREADS = 1 << 36
_ADD_REACTIONS = 1 << 6
_SEND_MESSAGES_IN_THREADS = 1 << 38
_READ_MESSAGE_HISTORY = 1 << 14  # 16384
_MEMBER_ALLOW = _VIEW_CHANNEL | _SEND_MESSAGES | _READ_MESSAGE_HISTORY

# Deny public viewers everything except viewing and reading history.
_EVERYONE_DENY = (
    _SEND_MESSAGES
    | _CREATE_PUBLIC_THREADS
    | _CREATE_PRIVATE_THREADS
    | _ADD_REACTIONS
    | _SEND_MESSAGES_IN_THREADS
)

# Retry config for transient Discord 5xx responses.
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFFS = (0.5, 1.5, 3.0)  # seconds between attempts 1→2, 2→3, 3→4


class DiscordClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            base_url=_DISCORD_API_BASE,
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"},
            timeout=10.0,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def _request_with_retry(
        self, method: str, url: str, **kwargs: Any
    ) -> httpx.Response:
        """Issue an httpx request, retrying on transient 5xx responses.

        Discord periodically returns 502/503/504 during partial outages. The
        REST endpoints we use here (create channel, send message, delete
        channel) are safe to retry — the worst case on a retried create is a
        duplicate channel, which hasn't been observed in practice because the
        first attempt either succeeds or fails before the request is accepted.
        """
        last_exc: httpx.HTTPStatusError | None = None
        for attempt in range(_RETRY_ATTEMPTS + 1):
            resp = await self._http.request(method, url, **kwargs)
            if resp.status_code < 500:
                resp.raise_for_status()
                return resp
            # 5xx — decide whether to retry.
            if attempt < _RETRY_ATTEMPTS:
                backoff = _RETRY_BACKOFFS[attempt]
                logger.warning(
                    f"[ChannelManager] Discord {resp.status_code} on "
                    f"{method} {url}; retrying in {backoff}s "
                    f"(attempt {attempt + 1}/{_RETRY_ATTEMPTS})"
                )
                await asyncio.sleep(backoff)
                continue
            # Final attempt failed: raise the underlying error.
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                raise
        # Unreachable — the loop either returns or raises.
        assert last_exc is not None
        raise last_exc

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
            # @everyone can view and read history but cannot send, react, or create threads
            {
                "id": str(guild_id),
                "type": 0,
                "allow": str(_VIEW_CHANNEL | _READ_MESSAGE_HISTORY),
                "deny": str(_EVERYONE_DENY),
            },
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

        resp = await self._request_with_retry(
            "POST",
            f"/guilds/{guild_id}/channels",
            json={
                "name": name,
                "type": 0,  # GUILD_TEXT
                "parent_id": str(category_id),
                "permission_overwrites": overwrites,
            },
        )
        return int(resp.json()["id"])

    async def send_message(
        self,
        channel_id: int,
        content: str,
        embeds: list[dict] | None = None,
    ) -> int:
        """Send a message to a channel. Returns the message snowflake ID."""
        payload: dict = {"content": content}
        if embeds:
            payload["embeds"] = embeds
        resp = await self._request_with_retry(
            "POST",
            f"/channels/{channel_id}/messages",
            json=payload,
        )
        return int(resp.json()["id"])

    async def delete_channel(self, channel_id: int) -> None:
        """Delete a guild channel."""
        await self._request_with_retry("DELETE", f"/channels/{channel_id}")
