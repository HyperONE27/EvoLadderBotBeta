import structlog
import discord
from discord import app_commands

from bot.components.embeds import (
    MatchesEmbed,
    QueueSnapshotEmbed,
    SystemStatsEmbed,
    UnsupportedGameModeEmbed,
)
from bot.core.config import BACKEND_URL, GAME_MODE_CHOICES
from bot.core.http import get_session
from bot.helpers.checks import check_if_admin

logger = structlog.get_logger(__name__)


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
                QueueSnapshotEmbed(queue),
                MatchesEmbed(active),
            ]
        )
