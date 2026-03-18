import discord


class ErrorEmbed(discord.Embed):
    """Standard red error embed used across all commands."""

    def __init__(self, title: str, description: str) -> None:
        super().__init__(
            title=title,
            description=description,
            color=discord.Color.red(),
        )
