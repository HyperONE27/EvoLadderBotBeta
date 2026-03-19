import structlog
import discord
from discord import app_commands

from bot.components.embeds import SetupIntroEmbed
from bot.components.views import SetupIntroView
from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from bot.helpers.checks import check_if_accepted_tos, check_if_banned, check_if_dm

logger = structlog.get_logger(__name__)


# --------------------
# Command registration
# --------------------


def register_setup_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="setup", description="Set up your player profile for matchmaking"
    )
    @app_commands.check(check_if_accepted_tos)
    @app_commands.check(check_if_banned)
    @app_commands.check(check_if_dm)
    async def setup_command(interaction: discord.Interaction) -> None:
        logger.debug(f"setup_command invoked by user={interaction.user.id}")
        await interaction.response.defer()

        modal_presets: dict[str, str] | None = None
        preselected_nationality: str | None = None
        preselected_location: str | None = None
        preselected_language: str | None = None

        try:
            async with get_session().get(
                f"{BACKEND_URL}/players/{interaction.user.id}"
            ) as response:
                data = await response.json()
                player = data.get("player")
                if player:
                    modal_presets = {
                        "player_name": player.get("player_name") or "",
                        "alt_ids": " ".join(player.get("alt_player_names") or []),
                        "battletag": player.get("battletag") or "",
                    }
                    preselected_nationality = player.get("nationality")
                    preselected_location = player.get("location")
                    preselected_language = player.get("language")
                    logger.debug(
                        f"setup_command: pre-populated data for user={interaction.user.id}"
                    )
        except Exception:
            logger.warning(
                f"setup_command: failed to fetch player data for user={interaction.user.id}, proceeding without pre-population",
                exc_info=True,
            )

        locale = get_player_locale(interaction.user.id)
        await interaction.followup.send(
            embed=SetupIntroEmbed(locale=locale),
            view=SetupIntroView(
                modal_presets=modal_presets,
                preselected_nationality=preselected_nationality,
                preselected_location=preselected_location,
                preselected_language=preselected_language,
                locale=locale,
            ),
        )
