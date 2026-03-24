import structlog
import discord
from discord import app_commands

from bot.components.embeds import ResolvePreviewEmbed
from bot.components.views import ResolveConfirmView, ResolveConfirmView2v2
from bot.core.config import GAME_MODE_CHOICES
from bot.core.dependencies import get_player_locale
from bot.helpers.checks import check_if_admin
from common.i18n import t

logger = structlog.get_logger(__name__)

RESULT_CHOICES_1V1 = [
    app_commands.Choice(name="Player 1 Wins", value="player_1_win"),
    app_commands.Choice(name="Player 2 Wins", value="player_2_win"),
    app_commands.Choice(name="Draw", value="draw"),
    app_commands.Choice(name="Invalidate", value="invalidated"),
]

RESULT_CHOICES_2V2 = [
    app_commands.Choice(name="Team 1 Wins", value="team_1_win"),
    app_commands.Choice(name="Team 2 Wins", value="team_2_win"),
    app_commands.Choice(name="Draw", value="draw"),
    app_commands.Choice(name="Invalidate", value="invalidated"),
]

# Combined set for autocomplete — includes all possible values.
ALL_RESULT_CHOICES = [
    app_commands.Choice(name="Player 1 / Team 1 Wins", value="player_1_win"),
    app_commands.Choice(name="Player 2 / Team 2 Wins", value="player_2_win"),
    app_commands.Choice(name="Team 1 Wins", value="team_1_win"),
    app_commands.Choice(name="Team 2 Wins", value="team_2_win"),
    app_commands.Choice(name="Draw", value="draw"),
    app_commands.Choice(name="Invalidate", value="invalidated"),
]


# --------------------
# Command registration
# --------------------


def register_admin_resolve_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="resolve", description="[Admin] Manually resolve a match result")
    @app_commands.check(check_if_admin)
    @app_commands.choices(game_mode=GAME_MODE_CHOICES, result=ALL_RESULT_CHOICES)
    async def resolve_command(
        interaction: discord.Interaction,
        match_id: int,
        result: app_commands.Choice[str],
        game_mode: app_commands.Choice[str] = None,  # type: ignore[assignment]
        reason: str | None = None,
    ) -> None:
        await interaction.response.defer()

        mode = game_mode.value if game_mode else "1v1"
        locale = get_player_locale(interaction.user.id)

        # Map 1v1-style result codes to 2v2-style when mode is 2v2.
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
        await interaction.followup.send(
            embed=ResolvePreviewEmbed(
                match_id, result_value, result_display, reason, locale=locale
            ),
            view=(
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
            ),
        )
