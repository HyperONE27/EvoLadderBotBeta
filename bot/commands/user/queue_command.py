import structlog
import discord
from discord import app_commands

from bot.components.embeds import QueueSetupEmbed1v1
from bot.components.views import (
    MatchFoundView1v1,
    MatchReportView1v1,
    QueueSetupView1v1,
)
from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from bot.helpers.checks import (
    check_if_accepted_tos,
    check_if_banned,
    check_if_completed_setup,
    check_if_dm,
    check_if_queueing,
)

logger = structlog.get_logger(__name__)

# Re-export for ws_listener and replay_handler imports.
__all__ = ["MatchFoundView1v1", "MatchReportView1v1", "register_queue_command"]


# --------------------
# Command registration
# --------------------


def register_queue_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="queue", description="Join the 1v1 ranked matchmaking queue")
    @app_commands.check(check_if_accepted_tos)
    @app_commands.check(check_if_completed_setup)
    @app_commands.check(check_if_queueing)
    @app_commands.check(check_if_banned)
    @app_commands.check(check_if_dm)
    async def queue_command(interaction: discord.Interaction) -> None:
        logger.debug(f"queue_command invoked by user={interaction.user.id}")
        await interaction.response.defer()

        bw_race: str | None = None
        sc2_race: str | None = None
        map_vetoes: list[str] = []

        try:
            async with get_session().get(
                f"{BACKEND_URL}/preferences_1v1/{interaction.user.id}"
            ) as resp:
                data = await resp.json()
                prefs = data.get("preferences")
                if prefs:
                    saved_races = prefs.get("last_chosen_races") or []
                    bw_race = next(
                        (r for r in saved_races if r.startswith("bw_")), None
                    )
                    sc2_race = next(
                        (r for r in saved_races if r.startswith("sc2_")), None
                    )
                    map_vetoes = prefs.get("last_chosen_vetoes") or []
        except Exception:
            logger.warning("Failed to load preferences", exc_info=True)

        locale = get_player_locale(interaction.user.id)
        embed = QueueSetupEmbed1v1(bw_race, sc2_race, map_vetoes, locale=locale)
        view = QueueSetupView1v1(
            discord_user_id=interaction.user.id,
            bw_race=bw_race,
            sc2_race=sc2_race,
            map_vetoes=map_vetoes,
        )
        await interaction.followup.send(embed=embed, view=view)
