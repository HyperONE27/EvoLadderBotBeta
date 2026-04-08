"""Discord /notifications — standalone version of the /setup notification step."""

from __future__ import annotations

import structlog

import discord
from discord import app_commands

from bot.components.embeds import SetupNotificationEmbed
from bot.components.views import SetupNotificationView
from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_cache, get_player_locale
from bot.core.http import get_session
from bot.helpers.checks import check_if_dm, check_player
from common.i18n import t

logger = structlog.get_logger(__name__)


def register_notifications_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="notifications",
        description=t("notifications_command.description.1", "enUS"),
    )
    @app_commands.check(check_if_dm)
    async def notifications_command(interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await check_player(interaction, accepted_tos=True, completed_setup=True)

        discord_uid = interaction.user.id
        locale = get_player_locale(discord_uid)

        # Fetch current preferences to pre-select the dropdowns.
        preselected_1v1: str | None = None
        preselected_2v2: str | None = None
        try:
            async with get_session().get(
                f"{BACKEND_URL}/notifications/{discord_uid}"
            ) as resp:
                notif = await resp.json()
            if notif:
                preselected_1v1 = (
                    "off"
                    if not notif.get("notify_queue_1v1")
                    else str(notif.get("notify_queue_1v1_cooldown", 15))
                )
                preselected_2v2 = (
                    "off"
                    if not notif.get("notify_queue_2v2")
                    else str(notif.get("notify_queue_2v2_cooldown", 15))
                )
                get_cache().notification_presets[discord_uid] = notif
        except Exception:
            logger.exception("Failed to fetch notifications for /notifications")

        view = SetupNotificationView(
            preselected_1v1=preselected_1v1,
            preselected_2v2=preselected_2v2,
            locale=locale,
            standalone=True,
        )
        view.message = await interaction.followup.send(  # type: ignore[func-returns-value]
            embed=SetupNotificationEmbed(locale=locale),
            view=view,
        )
