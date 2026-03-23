import structlog
import discord
from discord import app_commands

from bot.components.embeds import (
    ErrorEmbed,
    SetMMRPreviewEmbed,
    UnsupportedGameModeEmbed,
)
from bot.components.views import SetMMRConfirmView
from bot.core.config import BACKEND_URL, GAME_MODE_CHOICES
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from bot.helpers.checks import check_if_owner
from common.i18n import t
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
    @app_commands.describe(player="Ladder name, Discord username, or Discord ID")
    async def mmr_command(
        interaction: discord.Interaction,
        player: str,
        race: str,
        new_mmr: int,
        game_mode: app_commands.Choice[str] = None,  # type: ignore[assignment]
    ) -> None:
        await interaction.response.defer()

        mode = game_mode.value if game_mode else "1v1"
        locale = get_player_locale(interaction.user.id)

        if mode != "1v1":
            await interaction.followup.send(
                embed=UnsupportedGameModeEmbed(mode, locale=locale)
            )
            return

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
            f"Owner {interaction.user.name} ({interaction.user.id}) "
            f"invoked /mmr for {target_player_name} ({target_discord_uid}): "
            f"race={race}, new_mmr={new_mmr}"
        )
        await interaction.followup.send(
            embed=SetMMRPreviewEmbed(
                target_discord_uid, target_player_name, race, new_mmr, locale=locale
            ),
            view=SetMMRConfirmView(
                interaction.user.id,
                target_discord_uid,
                target_player_name,
                race,
                new_mmr,
            ),
        )
