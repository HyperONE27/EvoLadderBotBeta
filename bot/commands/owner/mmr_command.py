import structlog
import discord
from discord import app_commands

from bot.components.buttons import ConfirmButton, CancelButton
from bot.components.embeds import ErrorEmbed
from bot.core.config import BACKEND_URL, GAME_MODE_CHOICES
from bot.core.http import get_session
from bot.helpers.checks import check_if_owner
from bot.helpers.emotes import get_race_emote
from common.lookups.race_lookups import get_races

logger = structlog.get_logger(__name__)

# ----------
# Components
# ----------

# --- Embeds ---


class SetMMRPreviewEmbed(discord.Embed):
    def __init__(self, target: discord.User, race: str, new_mmr: int) -> None:
        try:
            race_emote = get_race_emote(race)
        except ValueError:
            race_emote = "🎮"

        super().__init__(
            title="⚠️ Set MMR",
            description=(
                f"You are about to set the MMR for:\n\n"
                f"**User:** {target.mention} (`{target.name}` / `{target.id}`)\n"
                f"**Race:** {race_emote} `{race}`\n"
                f"**New MMR:** `{new_mmr}`\n\n"
                "This is an **idempotent SET** — the MMR will be overwritten to this exact value.\n\n"
                "Please confirm below."
            ),
            color=discord.Color.orange(),
        )


class SetMMRSuccessEmbed(discord.Embed):
    def __init__(
        self,
        target: discord.User,
        race: str,
        old_mmr: int | None,
        new_mmr: int,
    ) -> None:
        try:
            race_emote = get_race_emote(race)
        except ValueError:
            race_emote = "🎮"

        old_str = str(old_mmr) if old_mmr is not None else "N/A"

        super().__init__(
            title="✅ MMR Updated",
            description=(
                f"**User:** {target.mention} (`{target.name}` / `{target.id}`)\n"
                f"**Race:** {race_emote} `{race}`\n"
                f"**Old MMR:** `{old_str}`\n"
                f"**New MMR:** `{new_mmr}`"
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


class SetMMRConfirmView(discord.ui.View):
    def __init__(
        self,
        caller_id: int,
        target: discord.User,
        race: str,
        new_mmr: int,
    ) -> None:
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            if interaction.user.id != caller_id:
                await interaction.response.send_message(
                    "You cannot use this button.", ephemeral=True
                )
                return
            await _send_set_mmr_request(interaction, target, race, new_mmr)

        self.add_item(ConfirmButton(callback=on_confirm))
        self.add_item(CancelButton())


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


async def _send_set_mmr_request(
    interaction: discord.Interaction,
    target: discord.User,
    race: str,
    new_mmr: int,
) -> None:
    async with get_session().put(
        f"{BACKEND_URL}/owner/mmr",
        json={
            "discord_uid": target.id,
            "race": race,
            "new_mmr": new_mmr,
        },
    ) as response:
        data = await response.json()

    if not data.get("success"):
        await interaction.response.edit_message(
            embed=ErrorEmbed(
                title="❌ Error",
                description="Failed to set MMR. The user may not have an MMR row for this race.",
            ),
            view=None,
        )
        return

    old_mmr = data.get("old_mmr")

    logger.info(
        f"Owner {interaction.user.name} ({interaction.user.id}) set MMR for "
        f"{target.name} ({target.id}): race={race}, {old_mmr} -> {new_mmr}"
    )

    await interaction.response.edit_message(
        embed=SetMMRSuccessEmbed(target, race, old_mmr, new_mmr),
        view=None,
    )


# --------------------
# Command registration
# --------------------


def register_owner_mmr_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="mmr", description="[Owner] Set a user's MMR value")
    @app_commands.check(check_if_owner)
    @app_commands.choices(game_mode=GAME_MODE_CHOICES)
    @app_commands.autocomplete(race=_autocomplete_race)
    async def mmr_command(
        interaction: discord.Interaction,
        user: discord.User,
        race: str,
        new_mmr: int,
        game_mode: app_commands.Choice[str] = None,  # type: ignore[assignment]
    ) -> None:
        await interaction.response.defer()

        mode = game_mode.value if game_mode else "1v1"

        if mode != "1v1":
            await interaction.followup.send(embed=UnsupportedGameModeEmbed(mode))
            return

        logger.info(
            f"Owner {interaction.user.name} ({interaction.user.id}) "
            f"invoked /mmr for {user.name} ({user.id}): race={race}, new_mmr={new_mmr}"
        )

        await interaction.followup.send(
            embed=SetMMRPreviewEmbed(user, race, new_mmr),
            view=SetMMRConfirmView(interaction.user.id, user, race, new_mmr),
        )
