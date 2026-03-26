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
from bot.core.config import ACTIVITY_CHART_BUCKET_MINUTES
from bot.helpers.activity_stats import build_activity_embed_fields
from bot.helpers.checks import (
    check_if_accepted_tos,
    check_if_banned,
    check_if_completed_setup,
    check_if_dm,
)
from bot.helpers.embed_branding import apply_default_embed_footer
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
            app_commands.Choice(name="2v2", value="2v2"),
            app_commands.Choice(name="FFA (soon)", value="FFA"),
        ]
    )
    async def activity_command(
        interaction: discord.Interaction,
        game_mode: str = "1v1",
    ) -> None:
        locale = get_player_locale(interaction.user.id)
        if game_mode not in ("1v1", "2v2"):
            uembed = discord.Embed(
                title=t("unsupported_game_mode_embed.title.1", locale),
                description=t(
                    "unsupported_game_mode_embed.description.1",
                    locale,
                    game_mode=game_mode,
                ),
                color=discord.Color.orange(),
            )
            apply_default_embed_footer(uembed, locale=locale)
            await interaction.response.send_message(
                embed=uembed,
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        end = utc_now()
        start = end - timedelta(hours=24)
        try:
            data = await fetch_queue_join_analytics(
                game_mode,
                start,
                end,
                bucket_minutes=ACTIVITY_CHART_BUCKET_MINUTES["24h"],
            )
            buckets = data.get("buckets") or []
            title = activity_chart_title(locale, game_mode, "24h")
            png = render_queue_join_chart_png(
                buckets,
                title=title,
                locale=locale,
                game_mode=game_mode,
                time_range="24h",
            )
            file = discord.File(png, filename="activity.png")
            embed = discord.Embed(
                title=title,
                description=t("activity_embed.description.24h.1", locale),
                color=discord.Color.dark_teal(),
            )
            for name, value, inline in build_activity_embed_fields(
                buckets, "24h", locale
            ):
                embed.add_field(name=name, value=value, inline=inline)
            apply_default_embed_footer(embed, locale=locale)
            view = ActivityChartView(game_mode, interaction.user.id, locale)
            await interaction.followup.send(embed=embed, file=file, view=view)
        except Exception:
            logger.exception("activity_command failed")
            await interaction.followup.send(
                t("activity_command.error.load_failed.1", locale),
                ephemeral=True,
            )
