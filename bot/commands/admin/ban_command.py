import structlog
import discord
from discord import app_commands

from bot.components.embeds import BanPreviewEmbed
from bot.components.views import BanConfirmView
from bot.helpers.checks import check_if_admin

logger = structlog.get_logger(__name__)


# --------------------
# Command registration
# --------------------


def register_admin_ban_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="ban", description="[Admin] Toggle a user's ban status")
    @app_commands.check(check_if_admin)
    async def ban_command(
        interaction: discord.Interaction,
        user: discord.User,
    ) -> None:
        await interaction.response.defer()
        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /ban for {user.name} ({user.id})"
        )
        await interaction.followup.send(
            embed=BanPreviewEmbed(user),
            view=BanConfirmView(interaction.user.id, user),
        )
