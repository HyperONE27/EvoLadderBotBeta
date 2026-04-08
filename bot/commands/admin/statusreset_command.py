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


# --------------------
# Command registration
# --------------------


def register_admin_statusreset_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="statusreset",
        description="[Admin] Reset a player's status to idle (fixes stuck players)",
    )
    @app_commands.describe(player="Ladder name, Discord username, or Discord ID")
    async def statusreset_command(
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
        current_status: str = target.get("player_status") or "idle"
        current_mode: str | None = target.get("current_match_mode")
        current_match_id: int | None = target.get("current_match_id")

        action = t("admin_statusreset.action", locale)
        target_label = (
            f"<@{target_discord_uid}> (`{target_player_name}` / `{target_discord_uid}`)"
        )

        def _mode_label(value: str | None) -> str:
            return value if value else t("shared.na", locale)

        def _match_id_label(value: int | None) -> str:
            return str(value) if value is not None else t("shared.na", locale)

        preview_changes = [
            (
                t("admin_statusreset.field.player_status", locale),
                current_status,
                "idle",
            ),
            (
                t("admin_statusreset.field.current_match_mode", locale),
                _mode_label(current_mode),
                t("shared.na", locale),
            ),
            (
                t("admin_statusreset.field.current_match_id", locale),
                _match_id_label(current_match_id),
                t("shared.na", locale),
            ),
        ]

        async def apply(
            btn_interaction: discord.Interaction,
        ) -> list[tuple[str, str, str]] | None:
            async with get_session().put(
                f"{BACKEND_URL}/admin/statusreset",
                json={
                    "discord_uid": target_discord_uid,
                    "admin_discord_uid": btn_interaction.user.id,
                },
            ) as response:
                data = await response.json()

            if response.status >= 400:
                btn_locale = get_player_locale(btn_interaction.user.id)
                error = data.get("detail") or t("error.unexpected_error", btn_locale)
                await btn_interaction.response.edit_message(
                    embed=ErrorEmbed(
                        title=t("error_embed.title.status_reset_failed", btn_locale),
                        description=t(
                            "error_embed.description.with_error",
                            btn_locale,
                            error=error,
                        ),
                        locale=btn_locale,
                    ),
                    view=None,
                )
                return None

            old_status = data.get("old_status")
            logger.info(
                f"Admin {btn_interaction.user.name} ({btn_interaction.user.id}) reset status for "
                f"{target_player_name} ({target_discord_uid}): {old_status} -> idle"
            )
            return [
                (
                    t("admin_statusreset.field.player_status", locale),
                    str(old_status) if old_status is not None else current_status,
                    "idle",
                ),
                (
                    t("admin_statusreset.field.current_match_mode", locale),
                    _mode_label(current_mode),
                    t("shared.na", locale),
                ),
                (
                    t("admin_statusreset.field.current_match_id", locale),
                    _match_id_label(current_match_id),
                    t("shared.na", locale),
                ),
            ]

        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /statusreset for {target_player_name} ({target_discord_uid})"
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
