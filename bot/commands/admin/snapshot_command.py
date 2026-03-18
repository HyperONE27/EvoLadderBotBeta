from datetime import datetime, timezone

import structlog
import discord
from discord import app_commands

from bot.core.config import BACKEND_URL
from bot.core.http import get_session
from bot.helpers.checks import check_if_admin
from common.lookups.race_lookups import get_race_by_code

logger = structlog.get_logger(__name__)

# ----------
# Constants
# ----------

GAME_MODE_CHOICES = [
    app_commands.Choice(name="1v1", value="1v1"),
    app_commands.Choice(name="2v2", value="2v2"),
    app_commands.Choice(name="FFA", value="ffa"),
]

MAX_QUEUE_SLOTS = 30
MAX_MATCH_SLOTS = 15

# ----------
# Components
# ----------

# --- Embeds ---


def _race_short(race_code: str | None) -> str:
    """Get 2-char short name for a race code, or '--'."""
    if not race_code:
        return "--"
    race = get_race_by_code(race_code)
    if race and race.get("short_name"):
        return race["short_name"][:2]
    return race_code[:2]


def _elapsed_seconds(iso_str: str | None) -> str:
    """Convert an ISO timestamp to an elapsed-seconds string like ' 794s'."""
    if not iso_str:
        return "   ?s"
    try:
        dt = datetime.fromisoformat(str(iso_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        elapsed = int((datetime.now(timezone.utc) - dt).total_seconds())
        return f"{elapsed:>4d}s"
    except Exception:
        return "   ?s"


def _format_queue_player(entry: dict) -> str:
    """Format a single queue player as a monospace backtick string.

    Alpha format: `R BW R SC CC PlayerName12 ` ` 794s`
    = rank(1) sp bw(2) sp rank(1) sp sc2(2) sp cc(2) sp name(12) = 25 chars.
    Missing fields use exact-width spaces as fallback.
    """
    player_name = (entry.get("player_name") or "Unknown")[:12]
    name_padded = f"{player_name:<12}"

    bw_race_code = entry.get("bw_race")
    sc2_race_code = entry.get("sc2_race")

    # rank(1) + space + race(2) per game, space-padded fallback
    bw_part = f"  {_race_short(bw_race_code)}" if bw_race_code else "    "  # 4 chars
    sc2_part = f"  {_race_short(sc2_race_code)}" if sc2_race_code else "    "  # 4 chars

    # country: 2 chars, not in queue entry
    cc = "  "  # 2 spaces

    # total: 4 + 1 + 4 + 1 + 2 + 1 + 12 = 25 chars
    player_str = f"{bw_part} {sc2_part} {cc} {name_padded}"
    wait_time = _elapsed_seconds(entry.get("joined_at"))

    return f"`{player_str}` `{wait_time}`"


def _format_blank_queue_slot() -> str:
    # 25 chars + 5 chars time, matching alpha blank slot
    return f"`{' ' * 25}` `{' ' * 5}`"


def _format_match_slot(match: dict, id_width: int) -> str:
    """Format a single active match as a monospace backtick string.

    Format: `  638` `R1 CC Player1Name ` `vs` `R2 CC Player2Name ` ` 794s`
    """
    match_id = match.get("id") or 0
    p1_name = (match.get("player_1_name") or "Unknown")[:12]
    p2_name = (match.get("player_2_name") or "Unknown")[:12]
    p1_race = _race_short(match.get("player_1_race"))
    p2_race = _race_short(match.get("player_2_race"))
    p1_padded = f"{p1_name:<12}"
    p2_padded = f"{p2_name:<12}"

    elapsed = _elapsed_seconds(match.get("assigned_at"))
    mid = f"{match_id:>{id_width}d}"

    return f"`{mid}` `{p1_race} {p1_padded}` `vs` `{p2_race} {p2_padded}` `{elapsed}`"


def _format_blank_match_slot(id_width: int) -> str:
    blank_id = " " * id_width
    blank_player = " " * 15  # race(2) + space + name(12)
    blank_time = " " * 5
    return f"`{blank_id}` `{blank_player}` `vs` `{blank_player}` `{blank_time}`"


class SystemStatsEmbed(discord.Embed):
    """Embed 1: DataFrame memory stats."""

    def __init__(self, dataframe_stats: dict) -> None:
        super().__init__(
            title="🔍 Admin System Snapshot",
            color=discord.Color.blue(),
        )

        if dataframe_stats:
            stat_lines: list[str] = []
            for table, info in dataframe_stats.items():
                rows = info.get("rows", 0) if isinstance(info, dict) else 0
                size_mb = info.get("size_mb", 0) if isinstance(info, dict) else 0
                stat_lines.append(f"{table:<20} {rows:>6} rows  {size_mb:>8.3f} MB")
            stats_block = "\n".join(stat_lines)
            self.add_field(
                name="📊 DataFrames",
                value=f"```\n{stats_block}\n```",
                inline=False,
            )
        else:
            self.add_field(
                name="📊 DataFrames",
                value="```\nNo stats available.\n```",
                inline=False,
            )


class QueueEmbed(discord.Embed):
    """Embed 2: Queue players in monospace backtick format, two columns of 15."""

    def __init__(self, queue: list[dict]) -> None:
        queue_size = len(queue)
        super().__init__(
            title="🎮 Queue Status",
            color=discord.Color.green(),
        )

        description = f"**Players in Queue:** {queue_size}\n"

        # Two columns of 15, paired: (0,1), (2,3), (4,5), ... (28,29)
        spacer = " \u200b \u200b \u200b "
        for i in range(0, MAX_QUEUE_SLOTS, 2):
            left = (
                _format_queue_player(queue[i])
                if i < len(queue)
                else _format_blank_queue_slot()
            )
            right = (
                _format_queue_player(queue[i + 1])
                if (i + 1) < len(queue)
                else _format_blank_queue_slot()
            )
            description += f"{left}{spacer}{right}\n"

        if queue_size > MAX_QUEUE_SLOTS:
            description += f"\n_... and {queue_size - MAX_QUEUE_SLOTS} more_"

        self.description = description


class MatchesEmbed(discord.Embed):
    """Embed 3: Active matches in monospace backtick format."""

    def __init__(self, active_matches: list[dict]) -> None:
        match_count = len(active_matches)
        super().__init__(
            title="⚔️ Active Matches",
            color=discord.Color.orange(),
        )

        # Determine ID column width
        id_width = 5
        if active_matches:
            max_id = max(m.get("id") or 0 for m in active_matches)
            id_width = max(5, len(str(max_id)))

        description = f"**Active Matches:** {match_count}\n"

        for i in range(MAX_MATCH_SLOTS):
            if i < len(active_matches):
                description += _format_match_slot(active_matches[i], id_width) + "\n"
            else:
                description += _format_blank_match_slot(id_width) + "\n"

        if match_count > MAX_MATCH_SLOTS:
            description += f"\n_... and {match_count - MAX_MATCH_SLOTS} more_"

        self.description = description


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

        await interaction.followup.send(
            embeds=[
                SystemStatsEmbed(stats),
                QueueEmbed(queue),
                MatchesEmbed(active),
            ]
        )
