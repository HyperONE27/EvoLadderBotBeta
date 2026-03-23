import structlog
import discord
from discord import app_commands

from bot.components.embeds import (
    MatchesEmbed,
    MatchesEmbed2v2,
    PartiesEmbed,
    QueueSnapshotEmbed,
    QueueSnapshotEmbed2v2,
    SystemStatsEmbed,
)
from bot.core.config import BACKEND_URL, GAME_MODE_CHOICES
from bot.core.dependencies import get_player_locale
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
        locale = get_player_locale(interaction.user.id)

        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /snapshot (mode={mode})"
        )

        if mode == "2v2":
            async with get_session().get(
                f"{BACKEND_URL}/admin/snapshot_2v2",
                params={"caller_uid": interaction.user.id},
            ) as response:
                data = await response.json()

            queue = data.get("queue") or []
            active = data.get("active_matches") or []
            parties = data.get("parties") or []
            stats = data.get("dataframe_stats") or {}
            await interaction.followup.send(
                embeds=[
                    SystemStatsEmbed(stats, locale=locale),
                    PartiesEmbed(parties, locale=locale),
                    QueueSnapshotEmbed2v2(queue, locale=locale),
                    MatchesEmbed2v2(active, locale=locale),
                ]
            )
        else:
            async with get_session().get(
                f"{BACKEND_URL}/admin/snapshot_1v1",
                params={"caller_uid": interaction.user.id},
            ) as response:
                data = await response.json()

            queue = data.get("queue") or []
            active = data.get("active_matches") or []
            stats = data.get("dataframe_stats") or {}
            await interaction.followup.send(
                embeds=[
                    SystemStatsEmbed(stats, locale=locale),
                    QueueSnapshotEmbed(queue, locale=locale),
                    MatchesEmbed(active, locale=locale),
                ]
            )
