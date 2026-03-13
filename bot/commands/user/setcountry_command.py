import discord
from discord import app_commands

from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_cache
from bot.core.http import get_session
from bot.helpers.checks import check_if_dm

# ----------
# Components
# ----------

# --- Embeds ---


# --- Views ---

# ----------------
# Internal helpers
# ----------------


async def _autocomplete_country(
    interaction: discord.Interaction,
    partial_country: str,
) -> list[app_commands.Choice[str]]:
    countries = get_cache().countries

    # Get all countries if no partial input, otherwise filter by name
    if partial_country:
        filtered_countries = [
            country
            for country in countries.values()
            if partial_country.lower() in country["name"].lower()
        ]
    else:
        filtered_countries = [country for country in countries.values()]

    # Sort alphabetically by name and take up to 25
    sorted_countries = sorted(filtered_countries, key=lambda c: c["name"])[:25]

    return [
        app_commands.Choice(name=country["name"], value=country["code"])
        for country in sorted_countries
    ]


# --------------------
# Command registration
# --------------------


def register_setcountry_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="setcountry", description="Set your country")
    @app_commands.check(check_if_dm)
    @app_commands.autocomplete(country=_autocomplete_country)
    async def setcountry_command(
        interaction: discord.Interaction, country: str
    ) -> None:
        await interaction.response.defer()

        async with get_session().put(
            f"{BACKEND_URL}/commands/setcountry",
            json={
                "discord_uid": interaction.user.id,
                "discord_username": interaction.user.name,
                "country_name": country,
            },
        ) as response:
            data = await response.json()

        await interaction.followup.send(data["message"])
