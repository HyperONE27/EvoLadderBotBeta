import structlog
import discord
from discord import app_commands

from bot.components.embeds import ResolvePreviewEmbed
from bot.components.views import ResolveConfirmView, ResolveConfirmView2v2
from bot.core.config import GAME_MODE_CHOICES
from bot.core.dependencies import get_player_locale
from bot.helpers.checks import check_admin
from common.i18n import t

logger = structlog.get_logger(__name__)

# Single choice list: values are player_1_win / player_2_win and are mapped to
# team_1_win / team_2_win at runtime when game_mode == "2v2".
RESULT_CHOICES = [
    app_commands.Choice(name="Player 1 / Team 1 Wins", value="player_1_win"),
    app_commands.Choice(name="Player 2 / Team 2 Wins", value="player_2_win"),
    app_commands.Choice(name="Draw", value="draw"),
    app_commands.Choice(name="Invalidate", value="invalidated"),
]


# --------------------
# Command registration
# --------------------


def register_admin_resolve_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="resolve", description="[Admin] Manually resolve a match result")
    @app_commands.choices(game_mode=GAME_MODE_CHOICES, result=RESULT_CHOICES)
    async def resolve_command(
        interaction: discord.Interaction,
        game_mode: app_commands.Choice[str],
        match_id: int,
        result: app_commands.Choice[str],
        reason: str | None = None,
    ) -> None:
        await interaction.response.defer()
        await check_admin(interaction)

        mode = game_mode.value
        locale = get_player_locale(interaction.user.id)

        # Map player_#_win → team_#_win for 2v2.
        result_value = result.value
        if mode == "2v2":
            if result_value == "player_1_win":
                result_value = "team_1_win"
            elif result_value == "player_2_win":
                result_value = "team_2_win"

        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /resolve {match_id} result={result_value} (mode={mode})"
        )

        result_display = t(f"resolve_result_display.{result_value}", locale)
        view = (
            ResolveConfirmView2v2(
                interaction.user.id,
                match_id,
                result_value,
                interaction.user.id,
                reason,
            )
            if mode == "2v2"
            else ResolveConfirmView(
                interaction.user.id,
                match_id,
                result_value,
                interaction.user.id,
                reason,
            )
        )
        view.message = await interaction.followup.send(  # type: ignore[func-returns-value]
            embed=ResolvePreviewEmbed(
                match_id, result_value, result_display, mode, reason, locale=locale
            ),
            view=view,
        )
