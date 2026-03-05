import discord
from discord import app_commands

# --------------------
# Command registration
# --------------------


def register_setcountry_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="setcountry", description="Set your country")
    async def setcountry_command(
        interaction: discord.Interaction, country: str
    ) -> None:
        await interaction.response.send_message(f"Set your country to {country}")