from datetime import datetime, timezone

import structlog
import discord
from discord import app_commands

from bot.core.config import BACKEND_URL
from bot.core.http import get_session
from bot.helpers.checks import check_if_admin
from bot.helpers.emotes import get_race_emote

logger = structlog.get_logger(__name__)

# ----------
# Constants
# ----------

GAME_MODE_CHOICES = [
    app_commands.Choice(name="1v1", value="1v1"),
    app_commands.Choice(name="2v2", value="2v2"),
    app_commands.Choice(name="FFA", value="ffa"),
]

# ----------
# Components
# ----------

# --- Embeds ---


class MatchNotFoundEmbed(discord.Embed):
    def __init__(self, match_id: int) -> None:
        super().__init__(
            title="❌ Match Not Found",
            description=f"No match found with ID `{match_id}`.",
            color=discord.Color.red(),
        )


class MatchInfoEmbed(discord.Embed):
    def __init__(self, match: dict) -> None:
        match_id = match.get("id", "?")
        result = match.get("match_result") or "In Progress"

        if result == "In Progress":
            color = discord.Color.blue()
        elif result == "invalidated":
            color = discord.Color.dark_grey()
        else:
            color = discord.Color.green()

        super().__init__(
            title=f"🔍 Match #{match_id} Details",
            color=color,
        )

        # --- Players ---
        p1_name = match.get("player_1_name") or "Unknown"
        p2_name = match.get("player_2_name") or "Unknown"
        p1_race = match.get("player_1_race") or "?"
        p2_race = match.get("player_2_race") or "?"
        p1_mmr = match.get("player_1_mmr") or 0
        p2_mmr = match.get("player_2_mmr") or 0
        p1_uid = match.get("player_1_discord_uid") or 0
        p2_uid = match.get("player_2_discord_uid") or 0

        try:
            p1_emote = get_race_emote(p1_race)
        except ValueError:
            p1_emote = "🎮"
        try:
            p2_emote = get_race_emote(p2_race)
        except ValueError:
            p2_emote = "🎮"

        players_text = (
            f"**Player 1:** {p1_emote} `{p1_name}` ({p1_race}) — {p1_mmr} MMR\n"
            f"  Discord: <@{p1_uid}> (`{p1_uid}`)\n"
            f"**Player 2:** {p2_emote} `{p2_name}` ({p2_race}) — {p2_mmr} MMR\n"
            f"  Discord: <@{p2_uid}> (`{p2_uid}`)"
        )
        self.add_field(name="👥 Players", value=players_text, inline=False)

        # --- Match Info ---
        map_name = match.get("map_name") or "Unknown"
        server = match.get("server_name") or "Unknown"
        info_text = f"**Map:** `{map_name}`\n**Server:** `{server}`"

        assigned_at = match.get("assigned_at")
        if assigned_at:
            try:
                dt = datetime.fromisoformat(str(assigned_at))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                info_text += f"\n**Assigned:** <t:{int(dt.timestamp())}:f>"
            except Exception:
                pass

        completed_at = match.get("completed_at")
        if completed_at:
            try:
                dt = datetime.fromisoformat(str(completed_at))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                info_text += f"\n**Completed:** <t:{int(dt.timestamp())}:f>"
            except Exception:
                pass

        self.add_field(name="🗺️ Match Info", value=info_text, inline=False)

        # --- Reports & Result ---
        p1_report = match.get("player_1_report") or "No report"
        p2_report = match.get("player_2_report") or "No report"
        p1_mmr_change = match.get("player_1_mmr_change")
        p2_mmr_change = match.get("player_2_mmr_change")

        result_text = (
            f"**P1 Report:** `{p1_report}`\n"
            f"**P2 Report:** `{p2_report}`\n"
            f"**Result:** `{result}`"
        )
        if p1_mmr_change is not None:
            result_text += f"\n**P1 MMR Change:** `{p1_mmr_change:+d}`"
        if p2_mmr_change is not None:
            result_text += f"\n**P2 MMR Change:** `{p2_mmr_change:+d}`"

        admin_intervened = match.get("admin_intervened", False)
        if admin_intervened:
            admin_uid = match.get("admin_discord_uid")
            result_text += f"\n**⚠️ Admin Intervened** by <@{admin_uid}>"

        self.add_field(name="📊 Reports & Result", value=result_text, inline=False)


class ReplayInfoEmbed(discord.Embed):
    def __init__(
        self,
        replays: list[dict],
        verifications: list[dict | None],
        replay_urls: list[str | None],
    ) -> None:
        super().__init__(
            title="📁 Replay Files",
            color=discord.Color.blue(),
        )

        if not replays:
            self.description = "No replays uploaded for this match."
            return

        for i, replay in enumerate(replays):
            verification = verifications[i] if i < len(verifications) else None
            url = replay_urls[i] if i < len(replay_urls) else None

            replay_hash = replay.get("replay_hash") or "?"
            upload_status = replay.get("upload_status") or "unknown"
            map_name = replay.get("map_name") or "Unknown"
            duration = replay.get("game_duration_seconds") or 0
            minutes = duration // 60
            seconds = duration % 60

            text = (
                f"**Hash:** `{replay_hash}`\n"
                f"**Status:** `{upload_status}`\n"
                f"**Map:** `{map_name}`\n"
                f"**Duration:** `{minutes}m {seconds}s`"
            )

            if url:
                text += f"\n**File:** [Download]({url})"

            if verification:
                checks: list[str] = []
                for key, val in verification.items():
                    if isinstance(val, bool):
                        icon = "✅" if val else "❌"
                        checks.append(f"{icon} {key}")
                if checks:
                    text += "\n**Verification:**\n" + "\n".join(checks)

            self.add_field(
                name=f"Replay #{i + 1}",
                value=text,
                inline=False,
            )


class UnsupportedGameModeEmbed(discord.Embed):
    def __init__(self, game_mode: str) -> None:
        super().__init__(
            title="🚧 Unsupported Game Mode",
            description=f"`{game_mode}` is not yet supported. Only `1v1` is currently available.",
            color=discord.Color.orange(),
        )


# ----------------
# Internal helpers
# ----------------


async def _fetch_match(match_id: int) -> dict:
    async with get_session().get(
        f"{BACKEND_URL}/admin/matches_1v1/{match_id}"
    ) as response:
        data: dict = await response.json()
        return data


# --------------------
# Command registration
# --------------------


def register_admin_match_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="match", description="[Admin] View full match details and replays"
    )
    @app_commands.check(check_if_admin)
    @app_commands.choices(game_mode=GAME_MODE_CHOICES)
    async def match_command(
        interaction: discord.Interaction,
        match_id: int,
        game_mode: app_commands.Choice[str] = None,  # type: ignore[assignment]
    ) -> None:
        await interaction.response.defer()

        mode = game_mode.value if game_mode else "1v1"

        if mode != "1v1":
            await interaction.followup.send(embed=UnsupportedGameModeEmbed(mode))
            return

        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /match {match_id} (mode={mode})"
        )

        data = await _fetch_match(match_id)
        match = data.get("match")

        if match is None:
            await interaction.followup.send(embed=MatchNotFoundEmbed(match_id))
            return

        replays = data.get("replays") or []
        verifications = data.get("verification") or []
        replay_urls = data.get("replay_urls") or []

        embeds: list[discord.Embed] = [MatchInfoEmbed(match)]
        if replays:
            embeds.append(ReplayInfoEmbed(replays, verifications, replay_urls))

        await interaction.followup.send(embeds=embeds)
