import structlog
import discord
from discord import app_commands

from bot.components.embeds import ToggleAdminPreviewEmbed
from bot.components.views import ToggleAdminConfirmView
from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from bot.helpers.checks import check_if_owner

logger = structlog.get_logger(__name__)


# --------------------
# Command registration
# --------------------


def register_owner_admin_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="admin", description="[Owner] Toggle a user's admin role")
    @app_commands.check(check_if_owner)
    @app_commands.describe(player="Ladder name, Discord username, or Discord ID")
    async def admin_command(
        interaction: discord.Interaction,
        player: str,
    ) -> None:
        await interaction.response.defer()

        async with get_session().get(f"{BACKEND_URL}/players/by_name/{player}") as resp:
            if resp.status == 404:
                await interaction.followup.send(
                    f"No player found matching **{player}**."
                )
                return
            data = await resp.json()

        target = data.get("player")
        if target is None:
            await interaction.followup.send(f"No player found matching **{player}**.")
            return

        target_discord_uid: int = target["discord_uid"]
        target_player_name: str = target["player_name"]
        target_discord_username: str = target["discord_username"]

        logger.info(
            f"Owner {interaction.user.name} ({interaction.user.id}) "
            f"invoked /admin for {target_player_name} ({target_discord_uid})"
        )
        locale = get_player_locale(interaction.user.id)
        await interaction.followup.send(
            embed=ToggleAdminPreviewEmbed(
                target_discord_uid, target_player_name, locale=locale
            ),
            view=ToggleAdminConfirmView(
                interaction.user.id,
                target_discord_uid,
                target_player_name,
                target_discord_username,
            ),
        )
