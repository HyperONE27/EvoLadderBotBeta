import discord
from discord import app_commands

from bot.components.embeds import HelpEmbed
from bot.core.dependencies import get_player_locale
from bot.helpers.checks import check_if_dm, check_player


def register_help_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="help", description="View a list of available commands")
    @app_commands.check(check_if_dm)
    async def help_command(interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await check_player(interaction, accepted_tos=True, completed_setup=True)
        locale = get_player_locale(interaction.user.id)
        await interaction.followup.send(embed=HelpEmbed(locale=locale))
