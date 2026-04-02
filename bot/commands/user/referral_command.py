"""Discord /referral — create or enter a referral code."""

from __future__ import annotations

import discord
from discord import app_commands

from bot.components.embeds import ReferralInitialEmbed
from bot.components.views import ReferralView
from bot.core.dependencies import get_cache, get_player_locale
from bot.helpers.checks import check_if_dm, check_player
from common.i18n import t


def register_referral_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="referral",
        description=t("referral_command.description.1", "enUS"),
    )
    @app_commands.check(check_if_dm)
    async def referral_command(interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await check_player(interaction, accepted_tos=True, completed_setup=True)
        locale = get_player_locale(interaction.user.id)
        cache = get_cache()
        player = cache.player_presets.get(interaction.user.id)
        p = player or {}
        already_referred = bool(p.get("referred_by") or p.get("referred_at"))
        view = ReferralView(already_referred=already_referred, locale=locale)
        view.message = await interaction.followup.send(  # type: ignore[func-returns-value]
            embed=ReferralInitialEmbed(locale=locale),
            view=view,
        )
