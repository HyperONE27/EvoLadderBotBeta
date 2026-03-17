import structlog
import discord
from discord import app_commands

from bot.components.buttons import ConfirmButton, CancelButton
from bot.core.config import BACKEND_URL
from bot.core.http import get_session
from bot.helpers.checks import check_if_admin

logger = structlog.get_logger(__name__)

# ----------
# Constants
# ----------

GAME_MODE_CHOICES = [
    app_commands.Choice(name="1v1", value="1v1"),
    app_commands.Choice(name="2v2", value="2v2"),
    app_commands.Choice(name="FFA", value="ffa"),
]

RESULT_CHOICES = [
    app_commands.Choice(name="Player 1 Wins", value="player_1_win"),
    app_commands.Choice(name="Player 2 Wins", value="player_2_win"),
    app_commands.Choice(name="Draw", value="draw"),
    app_commands.Choice(name="Invalidate", value="invalidated"),
]

# ----------
# Components
# ----------

# --- Embeds ---


class ResolvePreviewEmbed(discord.Embed):
    def __init__(
        self, match_id: int, result: str, result_display: str, reason: str | None
    ) -> None:
        super().__init__(
            title="⚠️ Admin Resolve Match",
            description=(
                f"You are about to manually resolve match **#{match_id}**.\n\n"
                f"**Result:** `{result_display}`\n"
                f"**Internal Code:** `{result}`"
            ),
            color=discord.Color.orange(),
        )
        assert self.description is not None
        if reason:
            self.description += f"\n**Reason:** {reason}"
        self.description += (
            "\n\n⚠️ This will:\n"
            "- Set the match result and calculate MMR changes\n"
            "- Mark the match as admin-intervened\n"
            "- Return both players to idle status\n"
            "- **Player report columns will NOT be modified**\n\n"
            "Please confirm below."
        )


class ResolveSuccessEmbed(discord.Embed):
    def __init__(self, data: dict) -> None:
        match_id = data.get("match_id", "?")
        result = data.get("match_result", "?")
        p1_name = data.get("player_1_name", "?")
        p2_name = data.get("player_2_name", "?")
        p1_change = data.get("player_1_mmr_change", 0)
        p2_change = data.get("player_2_mmr_change", 0)
        p1_new = data.get("player_1_new_mmr", "?")
        p2_new = data.get("player_2_new_mmr", "?")

        super().__init__(
            title=f"✅ Match #{match_id} Resolved",
            description=(
                f"**Result:** `{result}`\n\n"
                f"**{p1_name}:** `{p1_change:+d}` MMR → `{p1_new}` MMR\n"
                f"**{p2_name}:** `{p2_change:+d}` MMR → `{p2_new}` MMR"
            ),
            color=discord.Color.green(),
        )


class UnsupportedGameModeEmbed(discord.Embed):
    def __init__(self, game_mode: str) -> None:
        super().__init__(
            title="🚧 Unsupported Game Mode",
            description=f"`{game_mode}` is not yet supported. Only `1v1` is currently available.",
            color=discord.Color.orange(),
        )


# --- Views ---


class ResolveConfirmView(discord.ui.View):
    def __init__(
        self,
        caller_id: int,
        match_id: int,
        result: str,
        admin_discord_uid: int,
    ) -> None:
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            if interaction.user.id != caller_id:
                await interaction.response.send_message(
                    "You cannot use this button.", ephemeral=True
                )
                return
            await _send_resolve_request(
                interaction, match_id, result, admin_discord_uid
            )

        self.add_item(ConfirmButton(callback=on_confirm))
        self.add_item(CancelButton())


# ----------------
# Internal helpers
# ----------------


async def _send_resolve_request(
    interaction: discord.Interaction,
    match_id: int,
    result: str,
    admin_discord_uid: int,
) -> None:
    async with get_session().put(
        f"{BACKEND_URL}/admin/matches_1v1/{match_id}/resolve",
        json={
            "result": result,
            "admin_discord_uid": admin_discord_uid,
        },
    ) as response:
        data = await response.json()

    if not data.get("success"):
        error = data.get("error") or "An unexpected error occurred."
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="❌ Resolve Failed",
                description=error,
                color=discord.Color.red(),
            ),
            view=None,
        )
        return

    resolve_data = data.get("data") or {}
    logger.info(
        f"Admin {interaction.user.name} ({interaction.user.id}) resolved "
        f"match #{match_id}: result={result}"
    )

    await interaction.response.edit_message(
        embed=ResolveSuccessEmbed(resolve_data),
        view=None,
    )

    # Notify players via DM.
    await _notify_players(interaction, resolve_data)


async def _notify_players(
    interaction: discord.Interaction,
    data: dict,
) -> None:
    match_id = data.get("match_id", "?")
    result = data.get("match_result", "?")
    p1_uid = data.get("player_1_discord_uid")
    p2_uid = data.get("player_2_discord_uid")
    p1_name = data.get("player_1_name", "?")
    p2_name = data.get("player_2_name", "?")
    p1_change = data.get("player_1_mmr_change", 0)
    p2_change = data.get("player_2_mmr_change", 0)
    p1_new = data.get("player_1_new_mmr", "?")
    p2_new = data.get("player_2_new_mmr", "?")

    for uid, name, change, new_mmr in [
        (p1_uid, p1_name, p1_change, p1_new),
        (p2_uid, p2_name, p2_change, p2_new),
    ]:
        if uid is None:
            continue
        try:
            user = await interaction.client.fetch_user(uid)
            embed = discord.Embed(
                title=f"📋 Match #{match_id} — Admin Resolution",
                description=(
                    f"An administrator has manually resolved your match.\n\n"
                    f"**Result:** `{result}`\n"
                    f"**Your MMR Change:** `{change:+d}` → `{new_mmr}` MMR"
                ),
                color=discord.Color.blue(),
            )
            await user.send(embed=embed)
        except Exception:
            logger.warning(f"Failed to DM player {name} ({uid}) about resolve")


# --------------------
# Command registration
# --------------------


def register_admin_resolve_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="resolve", description="[Admin] Manually resolve a match result")
    @app_commands.check(check_if_admin)
    @app_commands.choices(game_mode=GAME_MODE_CHOICES, result=RESULT_CHOICES)
    async def resolve_command(
        interaction: discord.Interaction,
        match_id: int,
        result: app_commands.Choice[str],
        game_mode: app_commands.Choice[str] = None,  # type: ignore[assignment]
        reason: str | None = None,
    ) -> None:
        await interaction.response.defer()

        mode = game_mode.value if game_mode else "1v1"

        if mode != "1v1":
            await interaction.followup.send(embed=UnsupportedGameModeEmbed(mode))
            return

        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /resolve {match_id} result={result.value} (mode={mode})"
        )

        await interaction.followup.send(
            embed=ResolvePreviewEmbed(match_id, result.value, result.name, reason),
            view=ResolveConfirmView(
                interaction.user.id,
                match_id,
                result.value,
                interaction.user.id,
            ),
        )
