import discord

def cancel_embed() -> discord.Embed:
    return discord.Embed(
        title="❌ Operation Cancelled",
        description="This action has been cancelled.",
        color=discord.Color.red()
    )

def help_embed() -> discord.Embed:
    pass