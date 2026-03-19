import structlog
import discord
from discord import app_commands

from bot.components.embeds import SetMMRPreviewEmbed, UnsupportedGameModeEmbed
from bot.components.views import SetMMRConfirmView
from bot.core.config import GAME_MODE_CHOICES
from bot.helpers.checks import check_if_owner
from common.lookups.race_lookups import get_races

logger = structlog.get_logger(__name__)


# ----------------
# Internal helpers
# ----------------


async def _autocomplete_race(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    races = get_races()
    choices: list[app_commands.Choice[str]] = []
    for code, race in sorted(races.items(), key=lambda r: r[1]["name"]):
        if current.lower() in code.lower() or current.lower() in race["name"].lower():
            choices.append(app_commands.Choice(name=race["name"], value=code))
        if len(choices) >= 25:
            break
    return choices


# --------------------
# Command registration
# --------------------


def register_owner_mmr_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="mmr", description="[Owner] Set a user's MMR value")
    @app_commands.check(check_if_owner)
    @app_commands.choices(game_mode=GAME_MODE_CHOICES)
    @app_commands.autocomplete(race=_autocomplete_race)
    async def mmr_command(
        interaction: discord.Interaction,
        user: discord.User,
        race: str,
        new_mmr: int,
        game_mode: app_commands.Choice[str] = None,  # type: ignore[assignment]
    ) -> None:
        await interaction.response.defer()

        mode = game_mode.value if game_mode else "1v1"

        if mode != "1v1":
            await interaction.followup.send(embed=UnsupportedGameModeEmbed(mode))
            return

        logger.info(
            f"Owner {interaction.user.name} ({interaction.user.id}) "
            f"invoked /mmr for {user.name} ({user.id}): race={race}, new_mmr={new_mmr}"
        )

        await interaction.followup.send(
            embed=SetMMRPreviewEmbed(user, race, new_mmr),
            view=SetMMRConfirmView(interaction.user.id, user, race, new_mmr),
        )
