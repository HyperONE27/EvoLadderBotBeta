from typing import Any

import structlog
import discord
from discord import app_commands

from bot.components.embeds import ProfileNotFoundEmbed
from bot.components.views import ProfilePageView
from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_cache, get_player_locale
from bot.core.http import get_session
from bot.core.player_lookup import resolve_player_by_string
from bot.helpers.checks import (
    check_if_accepted_tos,
    check_if_admin,
    check_if_banned,
    check_if_completed_setup,
    check_if_dm,
)

logger = structlog.get_logger(__name__)


# ----------------
# Internal helpers
# ----------------


async def _fetch_profile(discord_uid: int) -> dict[str, Any]:
    async with get_session().get(f"{BACKEND_URL}/profile/{discord_uid}") as response:
        return await response.json()  # type: ignore[no-any-return]


# --------------------
# Command registration
# --------------------


def register_profile_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="profile", description="View your player profile")
    @app_commands.check(check_if_accepted_tos)
    @app_commands.check(check_if_completed_setup)
    @app_commands.check(check_if_banned)
    @app_commands.check(check_if_dm)
    @app_commands.describe(
        player="[Admin only] Ladder name, Discord username, or Discord ID"
    )
    async def profile_command(
        interaction: discord.Interaction,
        player: str | None = None,
    ) -> None:
        await interaction.response.defer()
        invoker_uid = interaction.user.id

        if player is not None:
            await check_if_admin(interaction)
            locale = get_player_locale(invoker_uid)
            target_player_row = await resolve_player_by_string(player)
            if target_player_row is None:
                await interaction.followup.send(
                    embed=ProfileNotFoundEmbed(locale=locale)
                )
                return
            target_uid: int = target_player_row["discord_uid"]
            target_user: (
                discord.User | discord.Member
            ) = await interaction.client.fetch_user(target_uid)
            logger.info(
                f"profile_command: admin={invoker_uid} viewing uid={target_uid}"
            )
        else:
            target_uid = invoker_uid
            target_user = interaction.user
            logger.info(f"profile_command invoked by user={invoker_uid}")

        data = await _fetch_profile(target_uid)
        player_data = data.get("player")

        if player_data is None:
            locale = get_player_locale(invoker_uid)
            await interaction.followup.send(embed=ProfileNotFoundEmbed(locale=locale))
            return

        if player is None:
            # Only update the locale cache when viewing your own profile.
            language = player_data.get("language")
            if language:
                get_cache().player_locales[invoker_uid] = language
        locale = get_player_locale(invoker_uid)

        mmrs_1v1: list[dict] = data.get("mmrs_1v1") or []
        mmrs_2v2: list[dict] = data.get("mmrs_2v2") or []
        notifications: dict | None = data.get("notifications")

        logger.info(
            f"profile_command: found player={player_data.get('player_name')!r} "
            f"mmrs_1v1={len(mmrs_1v1)} mmrs_2v2={len(mmrs_2v2)} for uid={target_uid}"
        )

        view = ProfilePageView(
            target_user,
            player_data,
            mmrs_1v1,
            mmrs_2v2,
            notifications,
            locale=locale,
            current_page="info",
        )
        view.message = await interaction.followup.send(  # type: ignore[func-returns-value]
            embed=view._build_embed(), view=view
        )
