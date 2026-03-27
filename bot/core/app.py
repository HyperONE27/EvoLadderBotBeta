import asyncio
import discord
import structlog
from discord import app_commands

from bot.commands.admin.ban_command import register_admin_ban_command
from bot.commands.admin.match_command import register_admin_match_command
from bot.commands.admin.resolve_command import register_admin_resolve_command
from bot.commands.admin.snapshot_command import register_admin_snapshot_command
from bot.commands.admin.statusreset_command import register_admin_statusreset_command
from bot.commands.owner.admin_command import register_owner_admin_command
from bot.commands.owner.mmr_command import register_owner_mmr_command
from bot.commands.user.activity_command import register_activity_command
from bot.commands.user.help_command import register_help_command
from bot.commands.user.leaderboard_command import register_leaderboard_command
from bot.commands.user.party_command import register_party_command
from bot.commands.user.profile_command import register_profile_command
from bot.commands.user.queue_command import register_queue_command
from bot.commands.user.setcountry_command import register_setcountry_command
from bot.commands.user.setup_command import register_setup_command
from bot.components.embeds import ErrorEmbed, LocaleSetupEmbed
from bot.components.views import LocaleSetupView
from bot.core.bootstrap import Bot
from bot.core.config import BACKEND_URL, BOT_TOKEN
from bot.core.dependencies import get_player_locale, set_bot
from bot.core.http import get_session, init_session, close_session
from bot.core.message_queue import get_message_queue, initialize_message_queue
from bot.core.ws_listener import start_ws_listener
from bot.helpers.replay_handler import handle_replay_upload
from common.i18n import t
from common.logging.config import configure_structlog

logger = structlog.get_logger(__name__)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Module-level flag to prevent re-initialization on reconnect.
_initialized: bool = False
_ws_task: asyncio.Task[None] | None = None

# ----------------
# Internal helpers
# ----------------


def _register_commands(client: discord.Client) -> None:
    register_admin_ban_command(tree)
    register_admin_match_command(tree)
    register_admin_resolve_command(tree)
    register_admin_snapshot_command(tree)
    register_admin_statusreset_command(tree)
    register_owner_admin_command(tree)
    register_owner_mmr_command(tree)
    register_activity_command(tree)
    register_help_command(tree)
    register_leaderboard_command(tree)
    # register_notifyme_command(tree)   # Deprecated(?): merged into /setup
    register_party_command(tree)
    register_profile_command(tree)
    # register_prune_command(tree)      # Deprecated: abandoned from alpha
    register_queue_command(tree)
    register_setcountry_command(tree)
    register_setup_command(tree)
    # register_termsofservice_command(tree)  # Deprecated: merged into /setup


# --------------------
# Basic event handlers
# --------------------


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author == client.user:
        return

    if isinstance(message.channel, discord.DMChannel):
        # Register the player if this is their first interaction with the bot.
        # If newly created, send the ToS + setup flow automatically.
        try:
            async with get_session().post(
                f"{BACKEND_URL}/players/register",
                json={
                    "discord_uid": message.author.id,
                    "discord_username": message.author.name,
                },
            ) as response:
                data = await response.json()
                if response.status < 400 and data.get("created"):
                    await message.channel.send(
                        embed=LocaleSetupEmbed(),
                        view=LocaleSetupView(
                            message.author.id,
                            message.author.name,
                            show_cancel=False,
                        ),
                    )
        except Exception:
            logger.warning(
                f"on_message: player registration check failed for user={message.author.id}",
                exc_info=True,
            )

        # Replay upload handler — only fires for DM messages with attachments.
        if message.attachments:
            await handle_replay_upload(client, message)


@client.event
async def on_connect() -> None:
    logger.info(f"🔗 [Discord Gateway] Bot established connection as {client.user}.")


@client.event
async def on_ready() -> None:
    global _initialized, _ws_task

    if _initialized:
        logger.info("[Discord Gateway] Bot reconnected (skipping re-initialization).")
        # Restart the WS listener if it died during disconnect.
        if _ws_task is None or _ws_task.done():
            _ws_task = asyncio.create_task(start_ws_listener(client))
        return

    await init_session()
    mq = initialize_message_queue()
    await mq.start()
    try:
        _register_commands(client)
        synced = await tree.sync()
        logger.info(f"[Discord Gateway] Synced {len(synced)} commands.")
        logger.info("[Discord Gateway] Bot is ready!")
        # Start WebSocket listener for real-time backend events.
        _ws_task = asyncio.create_task(start_ws_listener(client))
        _initialized = True
    except Exception as e:
        logger.error(f"[Discord Gateway] Error during initialization: {e}")
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
    from bot.helpers.checks import (
        AlreadyQueueingError,
        BannedError,
        NotAcceptedTosError,
        NotAdminError,
        NotCompletedSetupError,
        NotInDMError,
        NotOwnerError,
    )

    locale = get_player_locale(interaction.user.id)
    ephemeral = False
    if isinstance(error, app_commands.CheckFailure):
        if isinstance(error, NotInDMError):
            description = t("error.not_in_dm", locale)
            ephemeral = True
        elif isinstance(error, BannedError):
            description = t("error.banned", locale)
        elif isinstance(error, NotAdminError):
            description = t("error.not_admin", locale)
        elif isinstance(error, NotOwnerError):
            description = t("error.not_owner", locale)
        elif isinstance(error, NotAcceptedTosError):
            description = t("error.not_accepted_tos", locale)
        elif isinstance(error, NotCompletedSetupError):
            description = t("error.not_completed_setup", locale)
        elif isinstance(error, AlreadyQueueingError):
            description = t("error.already_queueing", locale)
        else:
            description = str(error) if str(error) else t("error.unauthorized", locale)

        embed = ErrorEmbed(
            title=t("error_embed.title.unauthorized_command", locale),
            description=description,
            locale=locale,
        )
    else:
        embed = ErrorEmbed(
            title=t("error_embed.title.unexpected_error", locale),
            description=t("error.unexpected_command", locale) + f"\nError: {error!r}",
            locale=locale,
        )

    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)


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
    await get_message_queue().stop()
    await close_session()
    logger.info("🛑 [Discord Gateway] Bot shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
