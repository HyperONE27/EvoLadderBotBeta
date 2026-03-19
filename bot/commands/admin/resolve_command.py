import structlog
import discord
from discord import app_commands

from bot.components.embeds import ResolvePreviewEmbed, UnsupportedGameModeEmbed
from bot.components.views import ResolveConfirmView
from bot.core.config import GAME_MODE_CHOICES
from bot.helpers.checks import check_if_admin

logger = structlog.get_logger(__name__)

RESULT_CHOICES = [
    app_commands.Choice(name="Player 1 Wins", value="player_1_win"),
    app_commands.Choice(name="Player 2 Wins", value="player_2_win"),
    app_commands.Choice(name="Draw", value="draw"),
    app_commands.Choice(name="Invalidate", value="invalidated"),
]


# --------------------
# Command registration
# --------------------


def register_admin_resolve_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="resolve", description="[Admin] Manually resolve a match result")
    @app_commands.check(check_if_admin)
    @app_commands.choices(game_mode=GAME_MODE_CHOICES, result=RESULT_CHOICES)
    async def resolve_command(
        interaction: discord.Interaction,
        match_id: int,
        result: app_commands.Choice[str],
        game_mode: app_commands.Choice[str] = None,  # type: ignore[assignment]
        reason: str | None = None,
    ) -> None:
        await interaction.response.defer()

        mode = game_mode.value if game_mode else "1v1"

        if mode != "1v1":
            await interaction.followup.send(embed=UnsupportedGameModeEmbed(mode))
            return

        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /resolve {match_id} result={result.value} (mode={mode})"
        )

        await interaction.followup.send(
            embed=ResolvePreviewEmbed(match_id, result.value, result.name, reason),
            view=ResolveConfirmView(
                interaction.user.id,
                match_id,
                result.value,
                interaction.user.id,
                reason,
            ),
        )
