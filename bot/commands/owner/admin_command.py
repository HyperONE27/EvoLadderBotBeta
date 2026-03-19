import structlog
import discord
from discord import app_commands

from bot.components.embeds import ToggleAdminPreviewEmbed
from bot.components.views import ToggleAdminConfirmView
from bot.core.dependencies import get_player_locale
from bot.helpers.checks import check_if_owner

logger = structlog.get_logger(__name__)


# --------------------
# Command registration
# --------------------


def register_owner_admin_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="admin", description="[Owner] Toggle a user's admin role")
    @app_commands.check(check_if_owner)
    async def admin_command(
        interaction: discord.Interaction,
        user: discord.User,
    ) -> None:
        await interaction.response.defer()
        logger.info(
            f"Owner {interaction.user.name} ({interaction.user.id}) "
            f"invoked /admin for {user.name} ({user.id})"
        )
        locale = get_player_locale(interaction.user.id)
        await interaction.followup.send(
            embed=ToggleAdminPreviewEmbed(user, locale=locale),
            view=ToggleAdminConfirmView(interaction.user.id, user),
        )
