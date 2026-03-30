"""Discord /referral — create or enter a referral code."""

from __future__ import annotations

import discord
from discord import app_commands

from bot.components.embeds import ReferralInitialEmbed
from bot.components.views import ReferralView
from bot.core.dependencies import get_cache, get_player_locale
from bot.helpers.checks import (
    check_if_accepted_tos,
    check_if_banned,
    check_if_completed_setup,
    check_if_dm,
)
from common.i18n import t


def register_referral_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="referral",
        description=t("referral_command.description.1", "enUS"),
    )
    @app_commands.check(check_if_accepted_tos)
    @app_commands.check(check_if_completed_setup)
    @app_commands.check(check_if_banned)
    @app_commands.check(check_if_dm)
    async def referral_command(interaction: discord.Interaction) -> None:
        locale = get_player_locale(interaction.user.id)
        cache = get_cache()
        player = cache.player_presets.get(interaction.user.id)
        already_referred = bool((player or {}).get("referred_by"))
        view = ReferralView(already_referred=already_referred, locale=locale)
        await interaction.response.send_message(
            embed=ReferralInitialEmbed(locale=locale),
            view=view,
        )
        view.message = await interaction.original_response()
