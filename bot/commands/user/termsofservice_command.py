import structlog
import discord
from discord import app_commands

from bot.components.embeds import TermsOfServiceEmbed
from bot.components.views import TermsOfServiceView
from bot.helpers.checks import check_if_banned, check_if_dm

logger = structlog.get_logger(__name__)


# --------------------
# Command registration
# --------------------


def register_termsofservice_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="termsofservice", description="View and accept the Terms of Service"
    )
    @app_commands.check(check_if_banned)
    @app_commands.check(check_if_dm)
    async def termsofservice_command(interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        discord_uid = interaction.user.id
        discord_username = interaction.user.name
        logger.info(f"User {discord_username} ({discord_uid}) opened Terms of Service")
        await interaction.followup.send(
            embed=TermsOfServiceEmbed(),
            view=TermsOfServiceView(discord_uid, discord_username),
        )
