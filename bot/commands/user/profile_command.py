import structlog
import discord
from discord import app_commands

from bot.components.embeds import ProfileEmbed, ProfileNotFoundEmbed
from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_cache, get_player_locale
from bot.core.http import get_session
from bot.helpers.checks import (
    check_if_accepted_tos,
    check_if_banned,
    check_if_completed_setup,
    check_if_dm,
)

logger = structlog.get_logger(__name__)


# ----------------
# Internal helpers
# ----------------


async def _fetch_profile(discord_uid: int) -> tuple[dict | None, list[dict]]:
    async with get_session().get(f"{BACKEND_URL}/profile/{discord_uid}") as response:
        data = await response.json()
    return data.get("player"), data.get("mmrs_1v1") or []


# --------------------
# Command registration
# --------------------


def register_profile_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="profile", description="View your player profile")
    @app_commands.check(check_if_accepted_tos)
    @app_commands.check(check_if_completed_setup)
    @app_commands.check(check_if_banned)
    @app_commands.check(check_if_dm)
    async def profile_command(interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        discord_uid = interaction.user.id
        logger.info(f"profile_command invoked by user={discord_uid}")

        player, mmrs = await _fetch_profile(discord_uid)

        if player is None:
            locale = get_player_locale(discord_uid)
            await interaction.followup.send(embed=ProfileNotFoundEmbed(locale=locale))
            return

        language = player.get("language")
        if language:
            get_cache().player_locales[discord_uid] = language
        locale = get_player_locale(discord_uid)

        logger.info(
            f"profile_command: found player={player.get('player_name')!r} "
            f"mmrs={len(mmrs)} for user={discord_uid}"
        )
        await interaction.followup.send(
            embed=ProfileEmbed(interaction.user, player, mmrs, locale=locale)
        )
