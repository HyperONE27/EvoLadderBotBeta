import discord
from discord import app_commands

from bot.core.config import BACKEND_URL
from bot.core.http import get_session
from bot.helpers.decorators import dm_only

# ----------------
# Internal helpers
# ----------------


# ------------------
# Command definition
# ------------------


# --------------------
# Command registration
# --------------------


def register_setcountry_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="setcountry", description="Set your country")
    @dm_only
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
