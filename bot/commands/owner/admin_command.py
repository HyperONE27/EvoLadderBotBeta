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


async def _fetch_current_role(discord_uid: int) -> str | None:
    """Return the current admin role string, or None if no admin row exists."""
    try:
        async with get_session().get(f"{BACKEND_URL}/admins/{discord_uid}") as resp:
            if resp.status >= 400:
                return None
            data = await resp.json()
            admin = data.get("admin") or None
            return admin.get("role") if admin else None
    except Exception:
        logger.warning(
            "Failed to fetch current admin role for preview",
            discord_uid=discord_uid,
        )
        return None


def _format_role(role: str | None, locale: str) -> str:
    if role is None or role == "inactive":
        return t("owner_admin.role.none", locale)
    return role


# --------------------
# Command registration
# --------------------


def register_owner_admin_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="admin", description="[Owner] Toggle a user's admin role")
    @app_commands.describe(player="Ladder name, Discord username, or Discord ID")
    async def admin_command(
        interaction: discord.Interaction,
        player: str,
    ) -> None:
        await interaction.response.defer()
        await check_admin(interaction, owner=True)

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
        target_discord_username: str = target["discord_username"]

        current_role = await _fetch_current_role(target_discord_uid)
        is_currently_admin = current_role is not None and current_role != "inactive"
        action = t(
            "owner_admin.action.demote"
            if is_currently_admin
            else "owner_admin.action.promote",
            locale,
        )
        target_label = (
            f"<@{target_discord_uid}> (`{target_player_name}` / `{target_discord_uid}`)"
        )
        predicted_role = "inactive" if is_currently_admin else "admin"
        preview_changes = [
            (
                t("owner_admin.field.role", locale),
                _format_role(current_role, locale),
                _format_role(predicted_role, locale),
            ),
        ]

        async def apply(
            btn_interaction: discord.Interaction,
        ) -> list[tuple[str, str, str]] | None:
            async with get_session().put(
                f"{BACKEND_URL}/owner/admin",
                json={
                    "discord_uid": target_discord_uid,
                    "discord_username": target_discord_username,
                    "owner_discord_uid": btn_interaction.user.id,
                },
            ) as response:
                data = await response.json()

            if response.status >= 400:
                btn_locale = get_player_locale(btn_interaction.user.id)
                error = data.get("detail") or t("error.unexpected_error", btn_locale)
                await btn_interaction.response.edit_message(
                    embed=ErrorEmbed(
                        title=t("error_embed.title.generic", btn_locale),
                        description=error,
                        locale=btn_locale,
                    ),
                    view=None,
                )
                return None

            new_role = data.get("new_role") or "unknown"
            action_kind = data.get("action") or "updated"
            logger.info(
                f"Owner {btn_interaction.user.name} ({btn_interaction.user.id}) toggled admin for "
                f"{target_player_name} ({target_discord_uid}): action={action_kind}, new_role={new_role}"
            )
            return [
                (
                    t("owner_admin.field.role", locale),
                    _format_role(current_role, locale),
                    _format_role(new_role, locale),
                ),
            ]

        logger.info(
            f"Owner {interaction.user.name} ({interaction.user.id}) "
            f"invoked /admin for {target_player_name} ({target_discord_uid})"
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
