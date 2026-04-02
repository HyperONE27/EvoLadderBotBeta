"""Discord /notifyme — opt-in anonymous DMs when someone joins the queue."""

from __future__ import annotations

import structlog

import discord
from discord import app_commands

from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from bot.helpers.checks import check_if_dm, check_player
from bot.components.embeds import (
    ErrorEmbed,
    NotifyMeSuccessEmbed,
    UnsupportedGameModeEmbed,
)
from common.i18n import t

logger = structlog.get_logger(__name__)


def register_notifyme_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="notifyme",
        description=t("notifyme_command.description.1", "enUS"),
    )
    @app_commands.describe(
        game_mode=t("notifyme_command.game_mode_param.1", "enUS"),
        enabled=t("notifyme_command.enabled_param.1", "enUS"),
        cooldown_minutes=t("notifyme_command.cooldown_param.1", "enUS"),
    )
    @app_commands.check(check_if_dm)
    @app_commands.choices(
        game_mode=[
            app_commands.Choice(name="1v1", value="1v1"),
            app_commands.Choice(name="2v2 (soon)", value="2v2"),
            app_commands.Choice(name="FFA (soon)", value="FFA"),
        ]
    )
    async def notifyme_command(
        interaction: discord.Interaction,
        enabled: bool,
        game_mode: str = "1v1",
        cooldown_minutes: int | None = None,
    ) -> None:
        locale = get_player_locale(interaction.user.id)
        if game_mode != "1v1":
            await interaction.response.send_message(
                embed=UnsupportedGameModeEmbed(game_mode, locale=locale),
                ephemeral=True,
            )
            return
        if cooldown_minutes is not None and (
            cooldown_minutes < 5 or cooldown_minutes > 1440
        ):
            await interaction.response.send_message(
                embed=ErrorEmbed(
                    title=t("error_embed.title.unauthorized_command", locale),
                    description=t("notifyme_command.error.cooldown_range.1", locale),
                    locale=locale,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        await check_player(interaction, accepted_tos=True, completed_setup=True)
        payload: dict = {
            "discord_uid": interaction.user.id,
            "notify_queue_1v1": enabled,
        }
        if cooldown_minutes is not None:
            if game_mode == "1v1":
                payload["notify_queue_1v1_cooldown"] = cooldown_minutes
            elif game_mode == "2v2":
                payload["notify_queue_2v2_cooldown"] = cooldown_minutes
            elif game_mode == "FFA":
                payload["notify_queue_ffa_cooldown"] = cooldown_minutes

        try:
            async with get_session().put(
                f"{BACKEND_URL}/notifications",
                json=payload,
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning(
                        "notifyme PUT failed",
                        status=resp.status,
                        body=text,
                    )
                    await interaction.followup.send(
                        embed=ErrorEmbed(
                            title=t("error_embed.title.unexpected_error", locale),
                            description=t(
                                "notifyme_command.error.save_failed.1", locale
                            ),
                            locale=locale,
                        ),
                        ephemeral=True,
                    )
                    return
            await interaction.followup.send(
                embed=NotifyMeSuccessEmbed(enabled, cooldown_minutes, locale=locale),
            )
        except Exception:
            logger.exception("notifyme_command failed")
            await interaction.followup.send(
                embed=ErrorEmbed(
                    title=t("error_embed.title.unexpected_error", locale),
                    description=t("notifyme_command.error.save_failed.1", locale),
                    locale=locale,
                ),
                ephemeral=True,
            )
