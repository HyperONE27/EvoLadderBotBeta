"""
Handles .SC2Replay DM uploads during an active match.

Called from the bot's on_message handler whenever a player sends a message
with attachments in a DM channel.
"""

import aiohttp
import structlog
import discord

from bot.components.embeds import (
    MatchInfoEmbed1v1,
    MatchInfoEmbed2v2,
    ReplayErrorEmbed,
    ReplaySuccessEmbed,
    ReplaySuccessEmbed2v2,
)
from bot.components.views import MatchReportView1v1, MatchReportView2v2
from bot.core.config import BACKEND_URL, ENABLE_REPLAY_VALIDATION
from bot.core.dependencies import get_cache, get_player_locale
from bot.core.http import get_session
from common.i18n import t
from bot.helpers.message_helpers import (
    queue_message_delete_low,
    queue_message_edit_high,
    queue_message_reply_high,
    queue_message_reply_low,
)

logger = structlog.get_logger(__name__)


async def handle_replay_upload(
    client: discord.Client, message: discord.Message
) -> None:
    """
    Entry point called by on_message.  Checks for a .SC2Replay attachment,
    validates the player is in a match, posts to the backend, and sends back
    a ReplayDetailsEmbed.
    """
    # Find the first .SC2Replay attachment.
    sc2_attachment: discord.Attachment | None = None
    for att in message.attachments:
        if att.filename.lower().endswith(".sc2replay"):
            sc2_attachment = att
            break

    if sc2_attachment is None:
        return  # No replay in this message.

    user_id = message.author.id
    cache = get_cache()

    match_info = cache.active_match_info.get(user_id)
    if match_info is None:
        locale = get_player_locale(user_id)
        await queue_message_reply_low(
            message,
            content=t("replay_handler.not_in_match", locale),
        )
        return

    match_data: dict = match_info["match_data"]
    match_id: int = match_data["id"]
    game_mode: str = match_data.get("game_mode", "1v1")

    processing_msg: discord.Message | None = None

    try:
        # Acknowledge immediately so the player knows we're working.
        locale = get_player_locale(user_id)
        processing_msg = await queue_message_reply_high(
            message, content=t("replay_handler.processing", locale)
        )

        replay_bytes = await sc2_attachment.read()

        form = aiohttp.FormData()
        form.add_field("discord_uid", str(user_id))
        form.add_field(
            "replay_file",
            replay_bytes,
            filename=sc2_attachment.filename,
            content_type="application/octet-stream",
        )

        mode_segment = "matches_2v2" if game_mode == "2v2" else "matches_1v1"
        async with get_session().post(
            f"{BACKEND_URL}/{mode_segment}/{match_id}/replay",
            data=form,
        ) as resp:
            data = await resp.json()

        if processing_msg is not None:
            await queue_message_delete_low(processing_msg)

        locale = get_player_locale(user_id)

        if resp.status >= 400:
            await queue_message_reply_high(
                message,
                embed=ReplayErrorEmbed(
                    data.get("detail") or "Unknown error", locale=locale
                ),
            )
            return

        parsed: dict = data["parsed"]
        verification: dict | None = data.get("verification")
        auto_resolved: bool = data.get("auto_resolved", False)

        # Send the replay details as a new message (high priority).
        replay_embed: discord.Embed
        if game_mode == "2v2":
            replay_embed = ReplaySuccessEmbed2v2(
                parsed,
                verification_results=verification,
                enforcement_enabled=ENABLE_REPLAY_VALIDATION,
                auto_resolved=auto_resolved,
                locale=locale,
            )
        else:
            replay_embed = ReplaySuccessEmbed(
                parsed,
                verification_results=verification,
                enforcement_enabled=ENABLE_REPLAY_VALIDATION,
                auto_resolved=auto_resolved,
                locale=locale,
            )
        await queue_message_reply_high(message, embed=replay_embed)

        # If auto-resolved, the WS match_completed event will handle
        # sending the finalized embed and disabling the dropdown.
        # No need to update the MatchInfoEmbed here.
        if auto_resolved:
            return

        # Update the MatchInfoEmbed message: refresh replay status and
        # (conditionally) unlock the report dropdown (high priority — gates reporting).
        match_msg = cache.active_match_messages.get(user_id)
        if match_msg is not None:
            should_unlock = (not ENABLE_REPLAY_VALIDATION) or _races_pass(verification)

            new_embed: discord.Embed
            new_view: discord.ui.View
            if game_mode == "2v2":
                player_infos: dict = match_info.get("player_infos", {})
                new_embed = MatchInfoEmbed2v2(
                    match_data, player_infos, replay_uploaded=True, locale=locale
                )
                new_view = MatchReportView2v2(
                    match_id, match_data, player_infos, locale=locale
                )
            else:
                p1_info: dict | None = match_info.get("p1_info")
                p2_info: dict | None = match_info.get("p2_info")
                p1_name = match_data.get("player_1_name", "Player 1")
                p2_name = match_data.get("player_2_name", "Player 2")
                new_embed = MatchInfoEmbed1v1(
                    match_data, p1_info, p2_info, replay_uploaded=True, locale=locale
                )
                new_view = MatchReportView1v1(
                    match_id,
                    p1_name,
                    p2_name,
                    match_data=match_data,
                    p1_info=p1_info,
                    p2_info=p2_info,
                    report_locked=not should_unlock,
                    locale=locale,
                )
            try:
                await queue_message_edit_high(match_msg, embed=new_embed, view=new_view)
            except Exception:
                logger.exception(
                    "[Replay] Failed to update MatchInfoEmbed after upload",
                    user_id=user_id,
                    match_id=match_id,
                )

    except Exception:
        logger.exception(
            "[Replay] Unexpected error during replay upload handling",
            user_id=user_id,
            match_id=match_id,
        )
        if processing_msg is not None:
            try:
                await queue_message_delete_low(processing_msg)
            except Exception:
                pass
        await queue_message_reply_high(
            message,
            content=t("replay_handler.unexpected_error", get_player_locale(user_id)),
        )


def _races_pass(verification: dict | None) -> bool:
    """Return True only if the races check passed (no critical failure)."""
    if verification is None:
        return False
    return bool(verification.get("races", {}).get("success", False))
