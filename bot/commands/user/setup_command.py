import structlog
import discord
from discord import app_commands

from bot.components.embeds import TermsOfServiceEmbed
from bot.components.views import TermsOfServiceSetupView
from bot.core.dependencies import get_player_locale
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
        locale = get_player_locale(discord_uid)
        await interaction.followup.send(
            embed=TermsOfServiceEmbed(locale=locale),
            view=TermsOfServiceSetupView(discord_uid, discord_username),
        )
