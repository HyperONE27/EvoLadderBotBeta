import structlog
import discord
from discord import app_commands

from bot.components.embeds import ErrorEmbed, StateChangePreviewEmbed
from bot.components.views import (
    ConfirmStateChangeView,
    _send_resolve_request,
    _send_resolve_request_2v2,
)
from bot.core.config import BACKEND_URL, GAME_MODE_CHOICES
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from bot.helpers.checks import check_admin
from common.datetime_helpers import ensure_utc, utc_now
from common.i18n import t

logger = structlog.get_logger(__name__)

# Single choice list: values are player_1_win / player_2_win and are mapped to
# team_1_win / team_2_win at runtime when game_mode == "2v2".
RESULT_CHOICES = [
    app_commands.Choice(name="Player 1 / Team 1 Wins", value="player_1_win"),
    app_commands.Choice(name="Player 2 / Team 2 Wins", value="player_2_win"),
    app_commands.Choice(name="Draw", value="draw"),
    app_commands.Choice(name="Invalidate", value="invalidated"),
]


_STALE_MATCH_THRESHOLD_HOURS = 24


async def _fetch_match(mode: str, match_id: int, caller_uid: int) -> dict | None:
    """Fetch a match row from the admin GET endpoint, or None on failure."""
    path = "matches_1v1" if mode == "1v1" else "matches_2v2"
    try:
        async with get_session().get(
            f"{BACKEND_URL}/admin/{path}/{match_id}",
            params={"caller_uid": caller_uid},
        ) as resp:
            if resp.status >= 400:
                return None
            data = await resp.json()
    except Exception:
        logger.warning(
            "Failed to fetch match for resolve preview",
            mode=mode,
            match_id=match_id,
        )
        return None
    match = data.get("match")
    return match if isinstance(match, dict) else None


# --------------------
# Command registration
# --------------------


def register_admin_resolve_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="resolve", description="[Admin] Manually resolve a match result")
    @app_commands.choices(game_mode=GAME_MODE_CHOICES, result=RESULT_CHOICES)
    async def resolve_command(
        interaction: discord.Interaction,
        game_mode: app_commands.Choice[str],
        match_id: int,
        result: app_commands.Choice[str],
        reason: str | None = None,
    ) -> None:
        await interaction.response.defer()
        await check_admin(interaction)

        mode = game_mode.value
        locale = get_player_locale(interaction.user.id)

        # Map player_#_win → team_#_win for 2v2.
        result_value = result.value
        if mode == "2v2":
            if result_value == "player_1_win":
                result_value = "team_1_win"
            elif result_value == "player_2_win":
                result_value = "team_2_win"

        match = await _fetch_match(mode, match_id, interaction.user.id)
        if match is None:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    title=t("error_embed.title.generic", locale),
                    description=t(
                        "admin_resolve.match_not_found", locale, match_id=str(match_id)
                    ),
                    locale=locale,
                )
            )
            return

        current_result_raw = match.get("match_result")
        current_result_display = (
            t(f"resolve_result_display.{current_result_raw}", locale)
            if current_result_raw
            else t("admin_resolve.result.unset", locale)
        )
        new_result_display = t(f"resolve_result_display.{result_value}", locale)

        action = t("admin_resolve.action", locale, mode=mode)
        target_label = t(
            "admin_resolve.target_label", locale, match_id=str(match_id), mode=mode
        )

        preview_changes = [
            (
                t("admin_resolve.field.match_result", locale),
                current_result_display,
                new_result_display,
            ),
        ]

        # 24h-old warning so admins notice if they typed the wrong match_id.
        warning: str | None = None
        assigned_at = ensure_utc(match.get("assigned_at"))
        if assigned_at is not None:
            age = utc_now() - assigned_at
            if age.total_seconds() > _STALE_MATCH_THRESHOLD_HOURS * 3600:
                hours = int(age.total_seconds() // 3600)
                warning = t(
                    "admin_resolve.warning.stale_match",
                    locale,
                    hours=str(hours),
                )

        async def apply(
            btn_interaction: discord.Interaction,
        ) -> list[tuple[str, str, str]] | None:
            # The existing helpers already edit the message in place with the
            # rich AdminResolution(2v2)Embed and DM/log on the side. Returning
            # None tells ConfirmStateChangeView not to overwrite that edit.
            if mode == "2v2":
                await _send_resolve_request_2v2(
                    btn_interaction,
                    match_id,
                    result_value,
                    btn_interaction.user.id,
                    reason,
                )
            else:
                await _send_resolve_request(
                    btn_interaction,
                    match_id,
                    result_value,
                    btn_interaction.user.id,
                    reason,
                )
            return None

        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /resolve {match_id} result={result_value} (mode={mode})"
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
                warning=warning,
                locale=locale,
            ),
            view=view,
        )
