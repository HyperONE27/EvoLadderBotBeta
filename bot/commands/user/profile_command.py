import discord

from bot.helpers.decorators import dm_only

# def register_profile_command()


@dm_only
async def profile_command(interaction: discord.Interaction):
    await interaction.response.send_message("Profile command")
