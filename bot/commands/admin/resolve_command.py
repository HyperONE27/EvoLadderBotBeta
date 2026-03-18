import structlog
import discord
from discord import app_commands

from bot.components.buttons import ConfirmButton, CancelButton
from bot.components.embeds import ErrorEmbed
from bot.core.config import BACKEND_URL, GAME_MODE_CHOICES, MATCH_LOG_CHANNEL_ID
from bot.core.http import get_session
from bot.helpers.checks import check_if_admin
from bot.helpers.emotes import get_flag_emote, get_race_emote, get_rank_emote
from bot.helpers.message_helpers import queue_channel_send_low, queue_user_send_low

logger = structlog.get_logger(__name__)

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
        description = (
            f"**Match ID:** {match_id}\n"
            f"**Resolution:** {result_display}\n"
            f"**Internal Code:** `{result}`"
        )
        if reason:
            description += f"\n**Reason:** {reason}"
        description += "\n\nThis will update the match result and MMR. Confirm?"
        super().__init__(
            title="⚠️ Admin: Confirm Match Resolution",
            description=description,
            color=discord.Color.orange(),
        )


def _player_prefix(race: str, nationality: str | None, letter_rank: str | None) -> str:
    """Build the prefix string: rank_emote flag race_emote."""
    parts: list[str] = []
    if letter_rank:
        try:
            parts.append(get_rank_emote(letter_rank))
        except ValueError:
            pass
    if nationality:
        parts.append(str(get_flag_emote(nationality)))
    try:
        parts.append(get_race_emote(race))
    except ValueError:
        parts.append("🎮")
    return " ".join(parts)


def _get_result_display(result: str, data: dict) -> str:
    """Build the result display string matching the alpha format."""
    p1_name = data.get("player_1_name", "?")
    p2_name = data.get("player_2_name", "?")
    p1_race = data.get("player_1_race", "")
    p2_race = data.get("player_2_race", "")

    try:
        p1_emote = get_race_emote(p1_race)
    except ValueError:
        p1_emote = "🎮"
    try:
        p2_emote = get_race_emote(p2_race)
    except ValueError:
        p2_emote = "🎮"

    if result == "player_1_win":
        return f"🏆 **{p1_emote} {p1_name}**"
    elif result == "player_2_win":
        return f"🏆 **{p2_emote} {p2_name}**"
    elif result == "draw":
        return "⚖️ **Draw**"
    elif result == "invalidated":
        return "❌ **Match Invalidated**"
    return result


class AdminResolutionEmbed(discord.Embed):
    """Admin Resolution embed — used for admin confirmation, player DMs,
    and match log channel."""

    def __init__(
        self,
        data: dict,
        *,
        reason: str | None,
        admin_name: str,
        is_admin_confirm: bool = False,
    ) -> None:
        match_id = data.get("match_id", "?")
        result = data.get("result", "?")
        p1_name = data.get("player_1_name", "?")
        p2_name = data.get("player_2_name", "?")
        p1_race = data.get("player_1_race", "")
        p2_race = data.get("player_2_race", "")
        p1_nationality = data.get("player_1_nationality")
        p2_nationality = data.get("player_2_nationality")
        p1_rank = data.get("player_1_letter_rank")
        p2_rank = data.get("player_2_letter_rank")
        p1_old = data.get("player_1_mmr", 0)
        p2_old = data.get("player_2_mmr", 0)
        p1_new = data.get("player_1_mmr_new", 0)
        p2_new = data.get("player_2_mmr_new", 0)
        p1_change = data.get("player_1_mmr_change", 0)
        p2_change = data.get("player_2_mmr_change", 0)

        p1_prefix = _player_prefix(p1_race, p1_nationality, p1_rank)
        p2_prefix = _player_prefix(p2_race, p2_nationality, p2_rank)

        title_icon = "✅" if is_admin_confirm else "⚖️"
        color = discord.Color.green() if is_admin_confirm else discord.Color.gold()

        super().__init__(
            title=f"{title_icon} Match #{match_id} Admin Resolution",
            description=(
                f"**{p1_prefix} {p1_name} ({p1_old} → {p1_new})** "
                f"vs "
                f"**{p2_prefix} {p2_name} ({p2_old} → {p2_new})**"
            ),
            color=color,
        )

        # Spacer
        self.add_field(name="", value="\u3164", inline=False)

        # Result (inline)
        result_display = _get_result_display(result, data)
        self.add_field(name="**Result:**", value=result_display, inline=True)

        # MMR Changes (inline)
        mmr_text = (
            f"• {p1_name}: `{p1_change:+d} ({p1_old} → {p1_new})`\n"
            f"• {p2_name}: `{p2_change:+d} ({p2_old} → {p2_new})`"
        )
        self.add_field(name="**MMR Changes:**", value=mmr_text, inline=True)

        # Admin intervention (full width)
        intervention_text = f"**Resolved by:** {admin_name}"
        if reason:
            intervention_text += f"\n**Reason:** {reason}"
        self.add_field(
            name="⚠️ **Admin Intervention:**",
            value=intervention_text,
            inline=False,
        )


class UnsupportedGameModeEmbed(discord.Embed):
    def __init__(self, game_mode: str) -> None:
        super().__init__(
            title="🚧 Unsupported Game Mode",
            description=(
                f"`{game_mode}` is not yet supported. Only `1v1` is currently available."
            ),
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
        reason: str | None,
    ) -> None:
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            if interaction.user.id != caller_id:
                await interaction.response.send_message(
                    "You cannot use this button.", ephemeral=True
                )
                return
            await _send_resolve_request(
                interaction, match_id, result, admin_discord_uid, reason
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
    reason: str | None,
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
            embed=ErrorEmbed(
                title="❌ Admin: Resolution Failed",
                description=f"Error: {error}",
            ),
            view=None,
        )
        return

    resolve_data = data.get("data") or {}
    admin_name = interaction.user.name
    logger.info(
        f"Admin {admin_name} ({interaction.user.id}) resolved "
        f"match #{match_id}: result={result}"
    )

    # Admin confirmation embed (green, shown in the command response).
    admin_embed = AdminResolutionEmbed(
        resolve_data, reason=reason, admin_name=admin_name, is_admin_confirm=True
    )
    await interaction.response.edit_message(embed=admin_embed, view=None)

    # Notify both players via DM and send to match log channel.
    await _notify_players(interaction, resolve_data, reason, admin_name)
    await _send_to_match_log(interaction, resolve_data, reason, admin_name)


async def _notify_players(
    interaction: discord.Interaction,
    data: dict,
    reason: str | None,
    admin_name: str,
) -> None:
    """DM both players with the Admin Resolution embed."""
    p1_uid = data.get("player_1_discord_uid")
    p2_uid = data.get("player_2_discord_uid")

    embed = AdminResolutionEmbed(data, reason=reason, admin_name=admin_name)

    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue
        try:
            user = await interaction.client.fetch_user(uid)
            await queue_user_send_low(user, embed=embed)
        except Exception:
            logger.warning(f"Failed to DM player {uid} about admin resolve")


async def _send_to_match_log(
    interaction: discord.Interaction,
    data: dict,
    reason: str | None,
    admin_name: str,
) -> None:
    """Send the Admin Resolution embed to the match log channel."""
    try:
        channel = interaction.client.get_channel(MATCH_LOG_CHANNEL_ID)
        if channel is None:
            channel = await interaction.client.fetch_channel(MATCH_LOG_CHANNEL_ID)
        if channel is not None:
            embed = AdminResolutionEmbed(data, reason=reason, admin_name=admin_name)
            await queue_channel_send_low(channel, embed=embed)  # type: ignore[arg-type]
    except Exception:
        logger.warning("Failed to send admin resolve embed to match log channel")


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
                reason,
            ),
        )
