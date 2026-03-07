import discord
from discord import app_commands

from bot.core.config import BACKEND_URL
from bot.core.http import get_session

# --------------------
# Command registration
# --------------------


def register_greeting_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="greet", description="Greet a player")
    async def greeting_command(interaction: discord.Interaction) -> None:

        await interaction.response.defer()

        async with get_session().get(
            f"{BACKEND_URL}/commands/greet/{interaction.user.id}"
        ) as response:
            data = await response.json()

        await interaction.followup.send(data["message"])
