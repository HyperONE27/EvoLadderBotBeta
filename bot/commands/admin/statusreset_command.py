import structlog
import discord
from discord import app_commands

from bot.components.embeds import StatusResetPreviewEmbed
from bot.components.views import StatusResetConfirmView
from bot.helpers.checks import check_if_admin

logger = structlog.get_logger(__name__)


# --------------------
# Command registration
# --------------------


def register_admin_statusreset_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="statusreset",
        description="[Admin] Reset a player's status to idle (fixes stuck players)",
    )
    @app_commands.check(check_if_admin)
    async def statusreset_command(
        interaction: discord.Interaction,
        user: discord.User,
    ) -> None:
        await interaction.response.defer()
        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /statusreset for {user.name} ({user.id})"
        )
        await interaction.followup.send(
            embed=StatusResetPreviewEmbed(user),
            view=StatusResetConfirmView(interaction.user.id, user),
        )
