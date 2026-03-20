"""Discord /notifyme — opt-in anonymous DMs when someone joins the queue."""

from __future__ import annotations

import structlog

import discord
from discord import app_commands

from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from bot.helpers.checks import (
    check_if_accepted_tos,
    check_if_banned,
    check_if_completed_setup,
    check_if_dm,
)
from bot.helpers.embed_branding import apply_default_embed_footer
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
    @app_commands.check(check_if_accepted_tos)
    @app_commands.check(check_if_completed_setup)
    @app_commands.check(check_if_banned)
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
            uembed = discord.Embed(
                title=t("unsupported_game_mode_embed.title.1", locale),
                description=t(
                    "unsupported_game_mode_embed.description.1",
                    locale,
                    game_mode=game_mode,
                ),
                color=discord.Color.orange(),
            )
            apply_default_embed_footer(uembed)
            await interaction.response.send_message(
                embed=uembed,
                ephemeral=True,
            )
            return
        if cooldown_minutes is not None and (
            cooldown_minutes < 5 or cooldown_minutes > 1440
        ):
            await interaction.response.send_message(
                t("notifyme_command.error.cooldown_range.1", locale),
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        payload: dict = {
            "discord_uid": interaction.user.id,
            "notify_queue_1v1": enabled,
        }
        if cooldown_minutes is not None:
            payload["queue_notify_cooldown_minutes"] = cooldown_minutes

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
                        t("notifyme_command.error.save_failed.1", locale),
                    )
                    return
            state = t(
                "notifyme_command.state.on.1"
                if enabled
                else "notifyme_command.state.off.1",
                locale,
            )
            cooldown_line = (
                t(
                    "notifyme_command.cooldown_line.1",
                    locale,
                    minutes=str(cooldown_minutes),
                )
                if cooldown_minutes is not None
                else ""
            )
            msg = t(
                "notifyme_command.success.1",
                locale,
                state=state,
                cooldown_line=cooldown_line,
            )
            await interaction.followup.send(msg)
        except Exception:
            logger.exception("notifyme_command failed")
            await interaction.followup.send(
                t("notifyme_command.error.save_failed.1", locale),
            )
