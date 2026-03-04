import discord

from functools import wraps
from typing import Any, Callable


def dm_only(func: Callable) -> Callable:
    @wraps(func)
    async def wrapper(interaction: discord.Interaction, *args, **kwargs) -> Any:
        if (
            interaction.channel is None
            or interaction.channel.type != discord.ChannelType.private
        ):
            await interaction.response.send_message(
                "This command can only be used in DMs."
            )
            return
        return await func(interaction, *args, **kwargs)

    return wrapper
