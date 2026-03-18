"""
Handles .SC2Replay DM uploads during an active match.

Called from the bot's on_message handler whenever a player sends a message
with attachments in a DM channel.
"""

import aiohttp
import structlog
import discord

from bot.core.config import BACKEND_URL, ENABLE_REPLAY_VALIDATION
from bot.core.dependencies import get_cache
from bot.core.http import get_session
from bot.components.replay_embed import ReplayErrorEmbed, ReplaySuccessEmbed
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
        await queue_message_reply_low(
            message,
            content=(
                "❌ You are not currently in an active match. "
                "Replay uploads are only accepted during an in-progress match."
            ),
        )
        return

    match_data: dict = match_info["match_data"]
    p1_info: dict | None = match_info["p1_info"]
    p2_info: dict | None = match_info["p2_info"]
    match_id: int = match_data["id"]

    # Acknowledge immediately so the player knows we're working.
    processing_msg = await queue_message_reply_high(
        message, content="⏳ Processing replay, please wait…"
    )

    try:
        replay_bytes = await sc2_attachment.read()

        form = aiohttp.FormData()
        form.add_field("discord_uid", str(user_id))
        form.add_field(
            "replay_file",
            replay_bytes,
            filename=sc2_attachment.filename,
            content_type="application/octet-stream",
        )

        async with get_session().post(
            f"{BACKEND_URL}/matches_1v1/{match_id}/replay",
            data=form,
        ) as resp:
            data = await resp.json()

        await queue_message_delete_low(processing_msg)

        if not data.get("success"):
            await queue_message_reply_high(
                message,
                embed=ReplayErrorEmbed(data.get("error") or "Unknown error"),
            )
            return

        parsed: dict = data["parsed"]
        verification: dict | None = data.get("verification")
        auto_resolved: bool = data.get("auto_resolved", False)

        # Lazily import to avoid circular import at module level.
        from bot.commands.user.queue_command import (
            MatchInfoEmbed,
            MatchReportView,
        )

        # Send the replay details as a new message (high priority).
        await queue_message_reply_high(
            message,
            embed=ReplaySuccessEmbed(
                parsed,
                verification_results=verification,
                enforcement_enabled=ENABLE_REPLAY_VALIDATION,
                auto_resolved=auto_resolved,
            ),
        )

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

            p1_name = match_data.get("player_1_name", "Player 1")
            p2_name = match_data.get("player_2_name", "Player 2")

            new_embed = MatchInfoEmbed(
                match_data, p1_info, p2_info, replay_uploaded=True
            )
            new_view = MatchReportView(
                match_id,
                p1_name,
                p2_name,
                match_data=match_data,
                p1_info=p1_info,
                p2_info=p2_info,
                report_locked=not should_unlock,
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
        try:
            await queue_message_delete_low(processing_msg)
        except Exception:
            pass
        await queue_message_reply_high(
            message,
            content="❌ An unexpected error occurred while processing the replay. Please try again.",
        )


def _races_pass(verification: dict | None) -> bool:
    """Return True only if the races check passed (no critical failure)."""
    if verification is None:
        return False
    return bool(verification.get("races", {}).get("success", False))
