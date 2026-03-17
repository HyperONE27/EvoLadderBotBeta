from datetime import datetime, timezone

import structlog
import discord
from discord import app_commands

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

# ----------
# Components
# ----------

# --- Embeds ---


class SnapshotEmbed(discord.Embed):
    def __init__(
        self,
        queue: list[dict],
        active_matches: list[dict],
        dataframe_stats: dict,
    ) -> None:
        super().__init__(
            title="📊 Server Snapshot (1v1)",
            color=discord.Color.blue(),
        )

        # --- Queue ---
        if queue:
            lines: list[str] = []
            for i, entry in enumerate(queue, 1):
                name = entry.get("player_name") or "Unknown"
                uid = entry.get("discord_uid") or 0
                bw_race = entry.get("bw_race") or "-"
                sc2_race = entry.get("sc2_race") or "-"
                bw_mmr = entry.get("bw_mmr") or "-"
                sc2_mmr = entry.get("sc2_mmr") or "-"
                wait = entry.get("wait_cycles") or 0

                joined_at = entry.get("joined_at")
                joined_str = "?"
                if joined_at:
                    try:
                        dt = datetime.fromisoformat(str(joined_at))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        joined_str = f"<t:{int(dt.timestamp())}:R>"
                    except Exception:
                        pass

                lines.append(
                    f"`{i}.` `{name}` (`{uid}`)\n"
                    f"   BW: `{bw_race}` (`{bw_mmr}`) | SC2: `{sc2_race}` (`{sc2_mmr}`) | "
                    f"Wait: `{wait}` | Joined: {joined_str}"
                )

            queue_text = "\n".join(lines)
        else:
            queue_text = "`No players in queue.`"

        self.add_field(
            name=f"📋 Queue ({len(queue)} player{'s' if len(queue) != 1 else ''})",
            value=queue_text[:1024],
            inline=False,
        )

        # --- Active Matches ---
        if active_matches:
            match_lines: list[str] = []
            for match in active_matches:
                mid = match.get("id") or "?"
                p1 = match.get("player_1_name") or "?"
                p2 = match.get("player_2_name") or "?"
                p1_race = match.get("player_1_race") or "?"
                p2_race = match.get("player_2_race") or "?"
                p1_mmr = match.get("player_1_mmr") or 0
                p2_mmr = match.get("player_2_mmr") or 0
                map_name = match.get("map_name") or "?"
                server = match.get("server_name") or "?"
                p1_report = match.get("player_1_report") or "pending"
                p2_report = match.get("player_2_report") or "pending"

                assigned_at = match.get("assigned_at")
                assigned_str = "?"
                if assigned_at:
                    try:
                        dt = datetime.fromisoformat(str(assigned_at))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        assigned_str = f"<t:{int(dt.timestamp())}:R>"
                    except Exception:
                        pass

                match_lines.append(
                    f"**Match #{mid}** — {assigned_str}\n"
                    f"  `{p1}` (`{p1_race}`, `{p1_mmr}`) vs `{p2}` (`{p2_race}`, `{p2_mmr}`)\n"
                    f"  Map: `{map_name}` | Server: `{server}`\n"
                    f"  Reports: `{p1_report}` / `{p2_report}`"
                )

            matches_text = "\n\n".join(match_lines)
        else:
            matches_text = "`No active matches.`"

        self.add_field(
            name=f"⚔️ Active Matches ({len(active_matches)})",
            value=matches_text[:1024],
            inline=False,
        )

        # --- DataFrame Stats ---
        if dataframe_stats:
            stat_lines: list[str] = []
            for table, info in dataframe_stats.items():
                rows = info.get("rows", 0) if isinstance(info, dict) else 0
                size_mb = info.get("size_mb", 0) if isinstance(info, dict) else 0
                stat_lines.append(f"`{table}`: `{rows}` rows, `{size_mb}` MB")
            stats_text = "\n".join(stat_lines)
        else:
            stats_text = "`No stats available.`"

        self.add_field(
            name="💾 DataFrame Memory",
            value=stats_text[:1024],
            inline=False,
        )


class UnsupportedGameModeEmbed(discord.Embed):
    def __init__(self, game_mode: str) -> None:
        super().__init__(
            title="🚧 Unsupported Game Mode",
            description=f"`{game_mode}` is not yet supported. Only `1v1` is currently available.",
            color=discord.Color.orange(),
        )


# --------------------
# Command registration
# --------------------


def register_admin_snapshot_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="snapshot",
        description="[Admin] View queue and active matches snapshot",
    )
    @app_commands.check(check_if_admin)
    @app_commands.choices(game_mode=GAME_MODE_CHOICES)
    async def snapshot_command(
        interaction: discord.Interaction,
        game_mode: app_commands.Choice[str] = None,  # type: ignore[assignment]
    ) -> None:
        await interaction.response.defer()

        mode = game_mode.value if game_mode else "1v1"

        if mode != "1v1":
            await interaction.followup.send(embed=UnsupportedGameModeEmbed(mode))
            return

        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /snapshot (mode={mode})"
        )

        async with get_session().get(f"{BACKEND_URL}/admin/snapshot_1v1") as response:
            data = await response.json()

        queue = data.get("queue") or []
        active = data.get("active_matches") or []
        stats = data.get("dataframe_stats") or {}

        await interaction.followup.send(embed=SnapshotEmbed(queue, active, stats))
