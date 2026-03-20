"""Discord /activity command — DM-only queue join chart."""

from __future__ import annotations

import structlog
from datetime import timedelta

import discord
from discord import app_commands

from bot.components.queue_activity_chart import render_queue_join_chart_png
from bot.components.views import ActivityChartView
from bot.core.dependencies import get_player_locale
from bot.helpers.activity_analytics import (
    activity_chart_title,
    fetch_queue_join_analytics,
)
from bot.helpers.checks import (
    check_if_accepted_tos,
    check_if_banned,
    check_if_completed_setup,
    check_if_dm,
)
from common.datetime_helpers import utc_now
from common.i18n import t

logger = structlog.get_logger(__name__)


def register_activity_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="activity",
        description=t("activity_command.description.1", "enUS"),
    )
    @app_commands.describe(
        game_mode=t("activity_command.game_mode_param.1", "enUS"),
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
    async def activity_command(
        interaction: discord.Interaction,
        game_mode: str = "1v1",
    ) -> None:
        locale = get_player_locale(interaction.user.id)
        if game_mode != "1v1":
            await interaction.response.send_message(
                embed=discord.Embed(
                    title=t("unsupported_game_mode_embed.title.1", locale),
                    description=t(
                        "unsupported_game_mode_embed.description.1",
                        locale,
                        game_mode=game_mode,
                    ),
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        end = utc_now()
        start = end - timedelta(hours=24)
        try:
            data = await fetch_queue_join_analytics(game_mode, start, end)
            buckets = data.get("buckets") or []
            title = activity_chart_title(locale, game_mode, "24h")
            png = render_queue_join_chart_png(buckets, title=title, locale=locale)
            file = discord.File(png, filename="activity.png")
            embed = discord.Embed(
                title=title,
                description=t("activity_embed.description.initial.1", locale),
                color=discord.Color.dark_teal(),
            )
            view = ActivityChartView(game_mode, interaction.user.id, locale)
            await interaction.followup.send(embed=embed, file=file, view=view)
        except Exception:
            logger.exception("activity_command failed")
            await interaction.followup.send(
                t("activity_command.error.load_failed.1", locale),
                ephemeral=True,
            )
