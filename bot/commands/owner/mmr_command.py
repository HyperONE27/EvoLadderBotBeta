import structlog
import discord
from discord import app_commands

from bot.components.embeds import (
    ErrorEmbed,
    StateChangePreviewEmbed,
    UnsupportedGameModeEmbed,
)
from bot.components.views import ConfirmStateChangeView
from bot.core.config import BACKEND_URL, GAME_MODE_CHOICES
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from bot.core.player_lookup import resolve_player_by_string
from bot.helpers.checks import check_admin
from common.i18n import t
from common.lookups.race_lookups import get_races

logger = structlog.get_logger(__name__)


# ----------------
# Internal helpers
# ----------------


async def _autocomplete_race(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    races = get_races()
    choices: list[app_commands.Choice[str]] = []
    for code, race in sorted(races.items(), key=lambda r: r[1]["name"]):
        if current.lower() in code.lower() or current.lower() in race["name"].lower():
            choices.append(app_commands.Choice(name=race["name"], value=code))
        if len(choices) >= 25:
            break
    return choices


async def _fetch_current_mmr(discord_uid: int, race: str) -> int | None:
    try:
        async with get_session().get(
            f"{BACKEND_URL}/mmrs_1v1/{discord_uid}/{race}"
        ) as resp:
            if resp.status >= 400:
                return None
            data = await resp.json()
            value = data.get("mmr")
            return int(value) if value is not None else None
    except Exception:
        logger.warning(
            "Failed to fetch current MMR for preview",
            discord_uid=discord_uid,
            race=race,
        )
        return None


# --------------------
# Command registration
# --------------------


def register_owner_mmr_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="mmr", description="[Owner] Set a user's MMR value")
    @app_commands.choices(game_mode=GAME_MODE_CHOICES)
    @app_commands.autocomplete(race=_autocomplete_race)
    @app_commands.describe(player="Ladder name, Discord username, or Discord ID")
    async def mmr_command(
        interaction: discord.Interaction,
        player: str,
        race: str,
        new_mmr: int,
        game_mode: app_commands.Choice[str] = None,  # type: ignore[assignment]
    ) -> None:
        await interaction.response.defer()
        await check_admin(interaction, owner=True)

        mode = game_mode.value if game_mode else "1v1"
        locale = get_player_locale(interaction.user.id)

        if mode != "1v1":
            await interaction.followup.send(
                embed=UnsupportedGameModeEmbed(mode, locale=locale)
            )
            return

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

        current_mmr = await _fetch_current_mmr(target_discord_uid, race)
        race_entry = get_races().get(race)
        race_name = race_entry["name"] if race_entry else race

        action = t("owner_mmr.action", locale, race=race_name)
        target_label = (
            f"<@{target_discord_uid}> (`{target_player_name}` / `{target_discord_uid}`)"
        )
        current_str = (
            str(current_mmr) if current_mmr is not None else t("shared.na", locale)
        )
        preview_changes = [
            (
                t("owner_mmr.field.mmr", locale, race=race_name),
                current_str,
                str(new_mmr),
            ),
        ]

        async def apply(
            btn_interaction: discord.Interaction,
        ) -> list[tuple[str, str, str]] | None:
            async with get_session().put(
                f"{BACKEND_URL}/owner/mmr",
                json={
                    "discord_uid": target_discord_uid,
                    "race": race,
                    "new_mmr": new_mmr,
                    "owner_discord_uid": btn_interaction.user.id,
                },
            ) as response:
                data = await response.json()

            if response.status >= 400:
                btn_locale = get_player_locale(btn_interaction.user.id)
                await btn_interaction.response.edit_message(
                    embed=ErrorEmbed(
                        title=t("error_embed.title.generic", btn_locale),
                        description=t("error_embed.description.mmr_failed", btn_locale),
                        locale=btn_locale,
                    ),
                    view=None,
                )
                return None

            old_mmr = data.get("old_mmr")
            old_str = str(old_mmr) if old_mmr is not None else t("shared.na", locale)
            logger.info(
                f"Owner {btn_interaction.user.name} ({btn_interaction.user.id}) set MMR for "
                f"{target_player_name} ({target_discord_uid}): race={race}, {old_mmr} -> {new_mmr}"
            )
            return [
                (
                    t("owner_mmr.field.mmr", locale, race=race_name),
                    old_str,
                    str(new_mmr),
                ),
            ]

        logger.info(
            f"Owner {interaction.user.name} ({interaction.user.id}) "
            f"invoked /mmr for {target_player_name} ({target_discord_uid}): "
            f"race={race}, new_mmr={new_mmr}"
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
