"""
Discord Gateway client for the channel manager.

Subscribes to guild message and message-edit events and appends them
to the channels table's messages JSONB log for audit purposes.
"""

import asyncio

import discord
import structlog

from channel_manager.database import ChannelDatabase

logger = structlog.get_logger(__name__)


def _make_client(db: ChannelDatabase) -> discord.Client:
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        logger.info(f"[ChannelManager Gateway] Connected as {client.user}")

    @client.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if db.get_channel_by_channel_id(message.channel.id) is None:
            return
        try:
            db.append_message(
                channel_id=message.channel.id,
                message_id=message.id,
                discord_uid=message.author.id,
                discord_username=message.author.name,
                content=message.content,
                ts=message.created_at.isoformat(),
            )
        except Exception:
            logger.exception(
                "[ChannelManager Gateway] Failed to log message",
                channel_id=message.channel.id,
            )

    @client.event
    async def on_message_edit(before: discord.Message, after: discord.Message) -> None:
        if after.author.bot:
            return
        if not isinstance(after.channel, discord.TextChannel):
            return
        if before.content == after.content:
            return
        if db.get_channel_by_channel_id(after.channel.id) is None:
            return
        ts = (
            after.edited_at.isoformat()
            if after.edited_at
            else after.created_at.isoformat()
        )
        try:
            db.append_edit(
                channel_id=after.channel.id,
                message_id=after.id,
                discord_uid=after.author.id,
                discord_username=after.author.name,
                original_content=before.content,
                new_content=after.content,
                ts=ts,
            )
        except Exception:
            logger.exception(
                "[ChannelManager Gateway] Failed to log edit",
                channel_id=after.channel.id,
            )

    return client


_BACKOFF_BASE = 5.0
_BACKOFF_BASE_RATELIMIT = 60.0
_BACKOFF_MAX = 300.0


async def start_gateway(db: ChannelDatabase, token: str) -> None:
    """Run the Discord gateway client, reconnecting with exponential backoff on failure.

    429 rate-limit errors use a longer initial backoff (60s) to avoid hammering
    the login endpoint while a global rate limit is active.
    """
    client = _make_client(db)
    backoff = _BACKOFF_BASE
    while True:
        try:
            await client.start(token, reconnect=True)
            backoff = _BACKOFF_BASE  # reset on clean exit
        except discord.HTTPException as exc:
            if exc.status == 429:
                wait = max(_BACKOFF_BASE_RATELIMIT, backoff)
                logger.warning(
                    "[ChannelManager Gateway] Rate limited (429), retrying",
                    wait=wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.exception(
                    "[ChannelManager Gateway] Fatal error, reconnecting", wait=backoff
                )
                await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)
            client = _make_client(db)
        except Exception:
            logger.exception(
                "[ChannelManager Gateway] Fatal error, reconnecting", wait=backoff
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)
            client = _make_client(db)
