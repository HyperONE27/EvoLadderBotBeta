import discord
from discord import app_commands

from bot.components.embeds import HelpEmbed
from bot.core.dependencies import get_player_locale
from bot.helpers.checks import check_if_dm


def register_help_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="help", description="View a list of available commands")
    @app_commands.check(check_if_dm)
    async def help_command(interaction: discord.Interaction) -> None:
        locale = get_player_locale(interaction.user.id)
        await interaction.response.send_message(embed=HelpEmbed(locale=locale))
