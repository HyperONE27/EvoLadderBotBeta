import structlog
import discord
from discord import app_commands

from bot.components.embeds import BanPreviewEmbed, ErrorEmbed
from bot.components.views import BanConfirmView
from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from bot.helpers.checks import check_if_admin
from common.i18n import t

logger = structlog.get_logger(__name__)


# --------------------
# Command registration
# --------------------


def register_admin_ban_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="ban", description="[Admin] Toggle a user's ban status")
    @app_commands.check(check_if_admin)
    @app_commands.describe(player="Ladder name, Discord username, or Discord ID")
    async def ban_command(
        interaction: discord.Interaction,
        player: str,
    ) -> None:
        await interaction.response.defer()

        locale = get_player_locale(interaction.user.id)

        async with get_session().get(f"{BACKEND_URL}/players/by_name/{player}") as resp:
            if resp.status == 404:
                await interaction.followup.send(
                    embed=ErrorEmbed(
                        title=t("error_embed.title.generic", locale),
                        description=t("error.player_not_found", locale, player=player),
                        locale=locale,
                    )
                )
                return
            data = await resp.json()

        target = data.get("player")
        if target is None:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    title=t("error_embed.title.generic", locale),
                    description=t("error.player_not_found", locale, player=player),
                    locale=locale,
                )
            )
            return

        target_discord_uid: int = target["discord_uid"]
        target_player_name: str = target["player_name"]

        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /ban for {target_player_name} ({target_discord_uid})"
        )
        await interaction.followup.send(
            embed=BanPreviewEmbed(
                target_discord_uid, target_player_name, locale=locale
            ),
            view=BanConfirmView(
                interaction.user.id, target_discord_uid, target_player_name
            ),
        )
