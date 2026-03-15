import structlog
import discord
from discord import app_commands

from bot.components.buttons import ConfirmButton, CancelButton
from bot.core.config import BACKEND_URL
from bot.core.http import get_session
from bot.helpers.checks import check_if_dm
from bot.helpers.emotes import get_flag_emote
from common.json_types import Country
from common.lookups.country_lookups import (
    get_countries,
    get_first_country_by_partial_name,
    search_countries_by_partial_name,
)

logger = structlog.get_logger(__name__)

# ----------
# Components
# ----------

# --- Embeds ---


class SetCountryNotFoundEmbed(discord.Embed):
    def __init__(self, country: str):
        super().__init__(
            title="❌ Country Not Found",
            description=f'No country found matching the string "{country}".',
            color=discord.Color.red(),
        )


class SetCountryPreviewEmbed(discord.Embed):
    def __init__(self, country: Country):
        super().__init__(
            title="🔍 Preview Nationality Selection",
            description="Please review your nationality selection before confirming:",
            color=discord.Color.blue(),
        )
        self.add_field(
            name=f"{get_flag_emote(country['code'])} **Nationality**",
            value=f"`{country['name']} ({country['code']})`",
        )


class SetCountryConfirmEmbed(discord.Embed):
    def __init__(self, country: Country):
        super().__init__(
            title="✅ Nationality Updated",
            description="Your nationality has been updated successfully.",
            color=discord.Color.blue(),
        )
        self.add_field(
            name=f"{get_flag_emote(country['code'])} **Nationality**",
            value=f"`{country['name']} ({country['code']})`",
        )


# --- Views ---


class SetCountryView(discord.ui.View):
    def __init__(self, country: Country):
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            await _send_setcountry_request(interaction, country)

        self.add_item(ConfirmButton(callback=on_confirm))
        self.add_item(CancelButton())


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
    await interaction.followup.send(
        embed=SetCountryPreviewEmbed(country),
        view=SetCountryView(country),
    )


async def _send_setcountry_request(
    interaction: discord.Interaction,
    country: Country,
) -> None:
    async with get_session().put(
        f"{BACKEND_URL}/commands/setcountry",
        json={
            "discord_uid": interaction.user.id,
            "discord_username": interaction.user.name,
            "country_code": country["code"],
        },
    ) as response:
        data = await response.json()

    if not data.get("success"):
        logger.error(
            f"setcountry backend failure for user={interaction.user.id}: {data.get('message')}"
        )
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="❌ Update Failed",
                description=data.get("message") or "An unexpected error occurred.",
                color=discord.Color.red(),
            ),
            view=None,
        )
        return

    await interaction.response.edit_message(
        embed=SetCountryConfirmEmbed(country),
        view=None,
    )


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

        country_obj = get_first_country_by_partial_name(country)
        if country_obj is None:
            await interaction.followup.send(embed=SetCountryNotFoundEmbed(country))
            return

        await _send_confirmation(interaction, country_obj)
