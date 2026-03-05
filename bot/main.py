import aiohttp
import asyncio
import discord
from discord import app_commands

from bot.config import BOT_TOKEN

from bot.commands.user.greeting_command import register_greeting_command
from bot.commands.user.setcountry_command import register_setcountry_command

from bot.http import init_session, close_session

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

tree = app_commands.CommandTree(client)

# ----------------
# Internal helpers
# ----------------


def _register_commands(client: discord.Client) -> None:
    """
    register_help_command(tree)
    register_leaderboard_command(tree)
    register_profile_command(tree)
    register_prune_command(tree)
    register_queue_command(tree)
    register_setcountry_command(tree)
    register_setup_command(tree)
    register_termsofservice_command(tree)
    """
    register_greeting_command(tree)
    register_setcountry_command(tree)
    pass


# --------------------
# Basic event handlers
# --------------------


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author == client.user:
        return
    if message.content.startswith("!"):
        await message.channel.send("Hello, world!")


@client.event
async def on_connect() -> None:
    print(f"🔗 [Discord Gateway] Bot established connection as {client.user}.")


@client.event
async def on_ready() -> None:
    await init_session()
    try:
        _register_commands(client)
        synced = await tree.sync()
        print(f"⌚ [Discord Gateway] Synced {len(synced)} commands.")

        print("✅ [Discord Gateway] Bot is ready!")
    except Exception as e:
        print(f"❌ [Discord Gateway] Error during initialization: {e}")
        raise e


@client.event
async def on_disconnect() -> None:
    print("⚠️ [Discord Gateway] Bot disconnected.")


@client.event
async def on_resumed() -> None:
    print("▶️ [Discord Gateway] Bot resumed.")


# ---------------
# Bot entry point
# ---------------


async def main() -> None:
    async with client:
        await client.start(token=BOT_TOKEN, reconnect=True)
    await close_session()

if __name__ == "__main__":
    asyncio.run(main())
