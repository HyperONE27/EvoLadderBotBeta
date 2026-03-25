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


async def start_gateway(db: ChannelDatabase, token: str) -> None:
    """Run the Discord gateway client, reconnecting automatically on failure."""
    client = _make_client(db)
    while True:
        try:
            await client.start(token, reconnect=True)
        except Exception:
            logger.exception("[ChannelManager Gateway] Fatal error, reconnecting in 5s")
            await asyncio.sleep(5)
            # Recreate client after a fatal error — the old one may be in a broken state.
            client = _make_client(db)
