import structlog
import discord
from discord import app_commands

from bot.components.embeds import ErrorEmbed, StateChangePreviewEmbed
from bot.components.views import ConfirmStateChangeView
from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from bot.core.player_lookup import resolve_player_by_string
from bot.helpers.checks import check_admin
from common.i18n import t

logger = structlog.get_logger(__name__)


def _ban_label(value: bool, locale: str) -> str:
    return t(
        "admin_ban.value.banned" if value else "admin_ban.value.not_banned",
        locale,
    )


# --------------------
# Command registration
# --------------------


def register_admin_ban_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="ban", description="[Admin] Toggle a user's ban status")
    @app_commands.describe(player="Ladder name, Discord username, or Discord ID")
    async def ban_command(
        interaction: discord.Interaction,
        player: str,
    ) -> None:
        await interaction.response.defer()
        await check_admin(interaction)

        locale = get_player_locale(interaction.user.id)

        target = await resolve_player_by_string(player)
        if target is None:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    title=t("error_embed.title.generic", locale),
                    description=t("error.player_not_found", locale, player=player),
                    locale=locale,
                )
            )
            return

        target_discord_uid: int = target["discord_uid"]
        target_player_name: str = target["player_name"]
        current_is_banned: bool = bool(target.get("is_banned", False))
        predicted_new = not current_is_banned

        action = t(
            "admin_ban.action.unban" if current_is_banned else "admin_ban.action.ban",
            locale,
        )
        target_label = (
            f"<@{target_discord_uid}> (`{target_player_name}` / `{target_discord_uid}`)"
        )
        preview_changes = [
            (
                t("admin_ban.field.is_banned", locale),
                _ban_label(current_is_banned, locale),
                _ban_label(predicted_new, locale),
            ),
        ]

        async def apply(
            btn_interaction: discord.Interaction,
        ) -> list[tuple[str, str, str]] | None:
            async with get_session().put(
                f"{BACKEND_URL}/admin/ban",
                json={
                    "discord_uid": target_discord_uid,
                    "admin_discord_uid": btn_interaction.user.id,
                },
            ) as response:
                data = await response.json()

            if response.status >= 400:
                btn_locale = get_player_locale(btn_interaction.user.id)
                await btn_interaction.response.edit_message(
                    embed=ErrorEmbed(
                        title=t("error_embed.title.generic", btn_locale),
                        description=t("error_embed.description.ban_failed", btn_locale),
                        locale=btn_locale,
                    ),
                    view=None,
                )
                return None

            new_is_banned: bool = data["new_is_banned"]
            logger.info(
                f"Admin {btn_interaction.user.name} ({btn_interaction.user.id}) toggled ban for "
                f"{target_player_name} ({target_discord_uid}): is_banned={new_is_banned}"
            )
            return [
                (
                    t("admin_ban.field.is_banned", locale),
                    _ban_label(current_is_banned, locale),
                    _ban_label(new_is_banned, locale),
                ),
            ]

        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /ban for {target_player_name} ({target_discord_uid})"
        )
        view = ConfirmStateChangeView(
            invoker_uid=interaction.user.id,
            action=action,
            target_label=target_label,
            apply=apply,
        )
        view.message = await interaction.followup.send(  # type: ignore[func-returns-value]
            embed=StateChangePreviewEmbed(
                action=action,
                target_label=target_label,
                changes=preview_changes,
                locale=locale,
            ),
            view=view,
        )
