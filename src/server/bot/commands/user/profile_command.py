import discord

from server.bot.helpers.decorators import dm_only


@dm_only
async def profile_command(interaction: discord.Interaction):
    await interaction.response.send_message("Profile command")
