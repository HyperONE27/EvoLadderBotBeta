"""Hidden `replays` keyword command for content creators.

Triggered from ``on_message`` in :mod:`bot.core.app` when a DM contains
exactly the word ``replays`` (case-insensitive, no prefix). Gated server-
side by the ``content_creators`` table; non-creators see no response.
"""

from __future__ import annotations

import structlog

import discord

from bot.components.caster_replay_view import CasterReplaySearchView
from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from bot.helpers.message_helpers import queue_user_send_low

logger = structlog.get_logger(__name__)


async def _is_content_creator(discord_uid: int) -> bool:
    try:
        async with get_session().get(
            f"{BACKEND_URL}/content_creators/{discord_uid}"
        ) as resp:
            if resp.status >= 400:
                return False
            data = await resp.json()
            return data.get("content_creator") is not None
    except Exception:
        logger.warning(
            "[caster] is_content_creator check failed",
            discord_uid=discord_uid,
            exc_info=True,
        )
        return False


async def handle_replays_message(
    client: discord.Client, message: discord.Message
) -> None:
    """Entry point called from ``on_message`` for the ``replays`` keyword."""
    caster_uid = message.author.id
    if not await _is_content_creator(caster_uid):
        return

    locale = get_player_locale(caster_uid)
    view = CasterReplaySearchView(caster_discord_uid=caster_uid, locale=locale)
    try:
        sent = await queue_user_send_low(message.author, view=view)
    except Exception:
        logger.exception(
            "[caster] failed to send replay search view", caster_uid=caster_uid
        )
        return
    if isinstance(sent, discord.Message):
        view.message = sent
