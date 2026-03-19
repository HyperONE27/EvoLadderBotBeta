import structlog
import discord
from discord import app_commands

from bot.components.embeds import SetCountryNotFoundEmbed, SetCountryPreviewEmbed
from bot.components.views import SetCountryView
from bot.core.dependencies import get_cache
from bot.helpers.checks import (
    check_if_accepted_tos,
    check_if_banned,
    check_if_completed_setup,
    check_if_dm,
)
from common.json_types import Country
from common.lookups.country_lookups import (
    get_countries,
    get_first_country_by_partial_name,
    search_countries_by_partial_name,
)

logger = structlog.get_logger(__name__)


# ----------------
# Internal helpers
# ----------------


async def _autocomplete_country(
    interaction: discord.Interaction,
    partial_country: str,
) -> list[app_commands.Choice[str]]:
    countries = (
        search_countries_by_partial_name(partial_country)
        if partial_country
        else get_countries()
    )

    # Sort alphabetically by name and take up to 25
    sorted_countries = sorted(countries.values(), key=lambda c: c["name"])[:25]

    return [
        app_commands.Choice(name=country["name"], value=country["name"])
        for country in sorted_countries
    ]


async def _send_confirmation(
    interaction: discord.Interaction,
    country: Country,
) -> None:
    locale = get_cache().player_locales.get(interaction.user.id, "enUS")
    await interaction.followup.send(
        embed=SetCountryPreviewEmbed(country, locale=locale),
        view=SetCountryView(country, locale=locale),
    )


# --------------------
# Command registration
# --------------------


def register_setcountry_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="setcountry", description="Set your country")
    @app_commands.check(check_if_accepted_tos)
    @app_commands.check(check_if_completed_setup)
    @app_commands.check(check_if_banned)
    @app_commands.check(check_if_dm)
    @app_commands.autocomplete(country=_autocomplete_country)
    async def setcountry_command(
        interaction: discord.Interaction, country: str
    ) -> None:
        await interaction.response.defer()

        country_obj = get_first_country_by_partial_name(country)
        if country_obj is None:
            locale = get_cache().player_locales.get(interaction.user.id, "enUS")
            await interaction.followup.send(
                embed=SetCountryNotFoundEmbed(country, locale=locale)
            )
            return

        await _send_confirmation(interaction, country_obj)
