import asyncio
import discord
import structlog
from discord import app_commands

from bot.core.bootstrap import Bot
from bot.core.config import BOT_TOKEN
from bot.core.dependencies import set_bot
from bot.core.http import init_session, close_session

from bot.commands.user.greeting_command import register_greeting_command
from bot.commands.user.profile_command import register_profile_command
from bot.commands.user.setcountry_command import register_setcountry_command
from bot.commands.user.setup_command import register_setup_command
from bot.commands.user.termsofservice_command import register_termsofservice_command
from common.logging.config import configure_structlog

logger = structlog.get_logger(__name__)

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
    register_admin_ban_command(tree)
    register_admin_match_command(tree)
    register_admin_resolve_command(tree)
    register_admin_snapshot_command(tree)
    register_admin_status_command(tree)
    reigster_owner_admin_command(tree)
    register_owner_mmr_command(tree)
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
    register_profile_command(tree)
    register_setcountry_command(tree)
    register_setup_command(tree)
    register_termsofservice_command(tree)


# --------------------
# Basic event handlers
# --------------------


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author == client.user:
        return
    # Remove this when we have actual things to do here
    if message.content.startswith("!"):
        await message.channel.send("🌎 Hello, world!")


@client.event
async def on_connect() -> None:
    logger.info(f"🔗 [Discord Gateway] Bot established connection as {client.user}.")


@client.event
async def on_ready() -> None:
    await init_session()
    try:
        _register_commands(client)
        synced = await tree.sync()
        logger.info(f"⌚ [Discord Gateway] Synced {len(synced)} commands.")
        logger.info("✅ [Discord Gateway] Bot is ready!")
    except Exception as e:
        logger.error(f"❌ [Discord Gateway] Error during initialization: {e}")
        raise e


@client.event
async def on_disconnect() -> None:
    logger.info("⏸️ [Discord Gateway] Bot disconnected.")


@client.event
async def on_resumed() -> None:
    logger.info("▶️ [Discord Gateway] Bot resumed.")


@tree.error
async def on_tree_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    if isinstance(error, app_commands.CheckFailure):
        description = (
            str(error)
            if str(error)
            else "You do not have permission to use this command."
        )

        embed = discord.Embed(
            title="🚫 Unauthorized Command Usage",
            description=description,
            color=discord.Color.red(),
        )
    else:
        embed = discord.Embed(
            title="❓ Unexpected Error",
            description="An unexpected error occurred. Please try again later.\n"
            "If the problem persists, please contact the developer.\n"
            f"Error: {error!r}",
            color=discord.Color.red(),
        )

    if interaction.response.is_done():
        await interaction.followup.send(embed=embed)
    else:
        await interaction.response.send_message(embed=embed)


# ---------------
# Bot entry point
# ---------------


async def main() -> None:
    configure_structlog(service_name="discord-bot")
    bot = Bot()
    set_bot(bot)
    logger.info("⚙️ [Bot] Bot initialized. Attempting to connect to Discord...")
    async with client:
        await client.start(token=BOT_TOKEN, reconnect=True)
    await close_session()
    logger.info("🛑 [Discord Gateway] Bot shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
