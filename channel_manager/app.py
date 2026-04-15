"""
Channel Manager microservice.

Exposes two endpoints:
  POST /channels/create                      — create a private Discord channel for a match
  DELETE /channels/by_match/{match_id}       — delete a channel when the match concludes

Also runs a Discord Gateway client that logs messages and edits in managed talk channels.

Entry point:
  uvicorn channel_manager.app:app --host 0.0.0.0 --port 8090
"""

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException

from channel_manager.config import (
    CHANNEL_DELETION_DELAY_SECONDS,
    DISCORD_BOT_TOKEN,
    DISCORD_CHANNEL_CATEGORY_ID,
    DISCORD_GUILD_ID,
    DISCORD_STAFF_ROLE_IDS,
)
from channel_manager.database import ChannelDatabase
from channel_manager.discord_http import DiscordClient
from channel_manager.gateway import start_gateway
from channel_manager.models import (
    ChannelCreateRequest,
    ChannelCreateResponse,
    ChannelDeleteResponse,
)
from common.logging.config import configure_structlog

logger = structlog.get_logger(__name__)

_db: ChannelDatabase | None = None
_discord: DiscordClient | None = None
_gateway_task: asyncio.Task[None] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_structlog(service_name="channel-manager")
    global _db, _discord, _gateway_task
    _db = ChannelDatabase()
    _discord = DiscordClient()
    _gateway_task = asyncio.create_task(start_gateway(_db, DISCORD_BOT_TOKEN))
    logger.info("[ChannelManager] Started.")
    yield
    _gateway_task.cancel()
    await _discord.close()
    logger.info("[ChannelManager] Shut down.")


app = FastAPI(lifespan=lifespan)


@app.post("/channels/create", response_model=ChannelCreateResponse)
async def create_channel(request: ChannelCreateRequest) -> ChannelCreateResponse:
    assert _db is not None and _discord is not None

    channel_name = f"ladder-{request.match_mode}-match-{request.match_id}"

    # Guard against duplicate requests: if a channel already exists for this
    # match, return it instead of creating a second Discord channel.
    existing = _db.get_channel_by_match_id(request.match_id, request.match_mode)
    if existing is not None:
        logger.warning(
            f"[ChannelManager] Channel already exists for match #{request.match_id} "
            f"({request.match_mode}), returning existing channel {existing['channel_id']}"
        )
        return ChannelCreateResponse(
            channel_id=int(existing["channel_id"]),
            message_url=existing.get("message_url")
            or f"https://discord.com/channels/{DISCORD_GUILD_ID}/{existing['channel_id']}",
        )

    try:
        channel_id = await _discord.create_channel(
            guild_id=DISCORD_GUILD_ID,
            category_id=DISCORD_CHANNEL_CATEGORY_ID,
            name=channel_name,
            allow_member_ids=request.discord_uids,
            allow_role_ids=DISCORD_STAFF_ROLE_IDS,
        )
    except Exception:
        logger.exception(
            f"[ChannelManager] Discord channel creation failed for match #{request.match_id}"
        )
        raise HTTPException(status_code=502, detail="Discord channel creation failed.")

    # Record the channel immediately, before any further Discord calls. This is
    # essential: if the welcome-message send below fails transiently, the row
    # still exists so the channel will be cleaned up when the match ends.
    # Without this step a failed send would orphan the Discord channel forever.
    _db.insert_channel(
        match_id=request.match_id,
        match_mode=request.match_mode,
        channel_id=channel_id,
    )

    # Ping all players and send a welcome embed.
    ping_content = " ".join(f"<@{uid}>" for uid in request.discord_uids)
    description = (
        "This channel has been created for your convenience. "
        "Please use it if you are unable to find your opponent in-game."
    )
    if DISCORD_STAFF_ROLE_IDS:
        staff_mention = f"<@&{DISCORD_STAFF_ROLE_IDS[0]}>"
        description += f" Feel free to ping {staff_mention} if you need assistance."
    welcome_embed = {
        "title": f"✉️ {request.match_mode} • Match #{request.match_id} • Talk Channel",
        "description": description,
        "color": 0x5865F2,  # Discord blurple
    }
    try:
        message_id = await _discord.send_message(
            channel_id, ping_content, embeds=[welcome_embed]
        )
    except Exception:
        # Welcome message failed even after retries. The channel still exists
        # and is already tracked in the DB, so it will be cleaned up on match
        # end. Fall back to a channel-root URL so players still get a usable
        # link in the DM embed.
        logger.exception(
            f"[ChannelManager] Failed to send welcome message in channel {channel_id}; "
            f"returning channel-root URL as fallback"
        )
        fallback_url = f"https://discord.com/channels/{DISCORD_GUILD_ID}/{channel_id}"
        logger.info(
            f"[ChannelManager] Created channel {channel_id} for match #{request.match_id} "
            f"(welcome message send failed)"
        )
        return ChannelCreateResponse(channel_id=channel_id, message_url=fallback_url)

    message_url = (
        f"https://discord.com/channels/{DISCORD_GUILD_ID}/{channel_id}/{message_id}"
    )
    _db.set_welcome_message(
        channel_id=channel_id,
        message_id=message_id,
        message_url=message_url,
    )

    logger.info(
        f"[ChannelManager] Created channel {channel_id} for match #{request.match_id}"
    )
    return ChannelCreateResponse(channel_id=channel_id, message_url=message_url)


@app.delete("/channels/by_match/{match_id}", response_model=ChannelDeleteResponse)
async def delete_channel_by_match(
    match_id: int,
    match_mode: str,
    delay_seconds: int = CHANNEL_DELETION_DELAY_SECONDS,
) -> ChannelDeleteResponse:
    assert _db is not None and _discord is not None

    row = _db.get_channel_by_match_id(match_id, match_mode)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"No active channel found for match #{match_id}."
        )

    channel_id: int = int(row["channel_id"])

    async def _do_delete() -> None:
        assert _db is not None and _discord is not None
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        try:
            await _discord.delete_channel(channel_id)
        except Exception:
            logger.exception(
                f"[ChannelManager] Discord deletion failed for channel {channel_id}"
            )
            return
        _db.mark_deleted(channel_id)
        logger.info(
            f"[ChannelManager] Deleted channel {channel_id} for match #{match_id}"
        )

    asyncio.create_task(_do_delete())
    return ChannelDeleteResponse(success=True)
