import structlog
import discord
from discord import app_commands

from bot.components.embeds import LocaleSetupEmbed
from bot.components.views import LocaleSetupView
from bot.core.dependencies import get_cache, get_player_locale
from bot.helpers.checks import check_if_banned, check_if_dm

logger = structlog.get_logger(__name__)


# --------------------
# Command registration
# --------------------


def register_setup_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="setup", description="Set up your player profile for matchmaking"
    )
    @app_commands.check(check_if_banned)
    @app_commands.check(check_if_dm)
    async def setup_command(interaction: discord.Interaction) -> None:
        logger.debug(f"setup_command invoked by user={interaction.user.id}")
        await interaction.response.defer()

        discord_uid = interaction.user.id
        discord_username = interaction.user.name

        # Pre-select the locale dropdown only for returning players who have
        # a persisted language preference. New players (no preset) start with
        # an empty dropdown so they must actively choose.
        preset = get_cache().player_presets.get(discord_uid)
        preselected_locale = (preset.get("language") if preset else None) or None
        show_cancel = bool(preset and preset.get("completed_setup"))

        locale = get_player_locale(discord_uid)
        await interaction.followup.send(
            embed=LocaleSetupEmbed(locale=locale),
            view=LocaleSetupView(
                discord_uid,
                discord_username,
                preselected_locale=preselected_locale,
                show_cancel=show_cancel,
            ),
        )
