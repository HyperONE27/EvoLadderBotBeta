import discord
import structlog
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

_ACTION_CHOICES: list[app_commands.Choice[str]] = [
    app_commands.Choice(name="Add", value="add"),
    app_commands.Choice(name="Remove", value="remove"),
]


async def _fetch_is_content_creator(discord_uid: int) -> bool:
    try:
        async with get_session().get(
            f"{BACKEND_URL}/content_creators/{discord_uid}"
        ) as resp:
            if resp.status >= 400:
                return False
            data = await resp.json()
            return data.get("content_creator") is not None
    except Exception:
        logger.warning(
            "Failed to fetch content-creator status",
            discord_uid=discord_uid,
            exc_info=True,
        )
        return False


def register_owner_caster_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="caster", description="[Owner] Add or remove a content creator")
    @app_commands.choices(action=_ACTION_CHOICES)
    @app_commands.describe(player="Ladder name, Discord username, or Discord ID")
    async def caster_command(
        interaction: discord.Interaction,
        player: str,
        action: app_commands.Choice[str],
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

        is_currently_caster = await _fetch_is_content_creator(target_discord_uid)
        action_value = action.value
        if action_value == "add":
            action_label = t("owner_caster.action.add", locale)
            predicted_status = t("owner_caster.status.caster", locale)
        else:
            action_label = t("owner_caster.action.remove", locale)
            predicted_status = t("owner_caster.status.none", locale)

        current_status = (
            t("owner_caster.status.caster", locale)
            if is_currently_caster
            else t("owner_caster.status.none", locale)
        )
        target_label = (
            f"<@{target_discord_uid}> (`{target_player_name}` / `{target_discord_uid}`)"
        )
        preview_changes = [
            (
                t("owner_caster.field.status", locale),
                current_status,
                predicted_status,
            ),
        ]

        async def apply(
            btn_interaction: discord.Interaction,
        ) -> list[tuple[str, str, str]] | None:
            async with get_session().put(
                f"{BACKEND_URL}/owner/caster",
                json={
                    "discord_uid": target_discord_uid,
                    "discord_username": target_discord_username,
                    "action": action_value,
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

            logger.info(
                f"Owner {btn_interaction.user.name} ({btn_interaction.user.id}) "
                f"{action_value}ed content creator {target_player_name} "
                f"({target_discord_uid})"
            )
            return [
                (
                    t("owner_caster.field.status", locale),
                    current_status,
                    predicted_status,
                ),
            ]

        view = ConfirmStateChangeView(
            invoker_uid=interaction.user.id,
            action=action_label,
            target_label=target_label,
            apply=apply,
        )
        view.message = await interaction.followup.send(  # type: ignore[func-returns-value]
            embed=StateChangePreviewEmbed(
                action=action_label,
                target_label=target_label,
                changes=preview_changes,
                locale=locale,
            ),
            view=view,
        )
