"""
Channel Manager microservice.

Exposes two endpoints:
  POST /channels/create                      — create a private Discord channel for a match
  DELETE /channels/by_match/{match_id}       — delete a channel when the match concludes

Entry point:
  uvicorn channel_manager.app:app --host 0.0.0.0 --port 8090
"""

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException

from channel_manager.config import (
    CHANNEL_DELETION_DELAY_SECONDS,
    DISCORD_CHANNEL_CATEGORY_ID,
    DISCORD_GUILD_ID,
    DISCORD_STAFF_ROLE_IDS,
)
from channel_manager.database import ChannelDatabase
from channel_manager.discord_http import DiscordClient
from channel_manager.models import (
    ChannelCreateRequest,
    ChannelCreateResponse,
    ChannelDeleteResponse,
    ChannelMessageRequest,
    ChannelMessageResponse,
)
from common.logging.config import configure_structlog

logger = structlog.get_logger(__name__)

_db: ChannelDatabase | None = None
_discord: DiscordClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    configure_structlog(service_name="channel-manager")
    global _db, _discord
    _db = ChannelDatabase()
    _discord = DiscordClient()
    logger.info("[ChannelManager] Started.")
    yield
    await _discord.close()
    logger.info("[ChannelManager] Shut down.")


app = FastAPI(lifespan=lifespan)


@app.post("/channels/create", response_model=ChannelCreateResponse)
async def create_channel(request: ChannelCreateRequest) -> ChannelCreateResponse:
    assert _db is not None and _discord is not None

    channel_name = f"ladder-{request.match_mode}-match-{request.match_id}"

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
        logger.exception(
            f"[ChannelManager] Failed to send ping message in channel {channel_id}"
        )
        raise HTTPException(status_code=502, detail="Failed to send channel message.")

    message_url = (
        f"https://discord.com/channels/{DISCORD_GUILD_ID}/{channel_id}/{message_id}"
    )

    _db.insert_channel(
        match_id=request.match_id,
        match_mode=request.match_mode,
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
    delay_seconds: int = CHANNEL_DELETION_DELAY_SECONDS,
) -> ChannelDeleteResponse:
    assert _db is not None and _discord is not None

    row = _db.get_channel_by_match_id(match_id)
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


@app.post("/channels/{channel_id}/messages", response_model=ChannelMessageResponse)
async def log_channel_message(
    channel_id: int,
    request: ChannelMessageRequest,
) -> ChannelMessageResponse:
    """Append a player message to the channel's audit log."""
    assert _db is not None
    try:
        _db.append_message(
            channel_id=channel_id,
            discord_uid=request.discord_uid,
            content=request.content,
            ts=request.timestamp,
        )
    except Exception:
        logger.exception(
            f"[ChannelManager] Failed to log message for channel {channel_id}"
        )
        raise HTTPException(status_code=502, detail="Failed to log message.")
    return ChannelMessageResponse(success=True)
