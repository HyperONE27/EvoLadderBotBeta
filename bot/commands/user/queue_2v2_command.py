import structlog
import discord
from discord import app_commands

from bot.components.embeds import QueueSetupEmbed2v2
from bot.components.views import QueueSetupView2v2
from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from bot.helpers.checks import (
    check_if_accepted_tos,
    check_if_banned,
    check_if_completed_setup,
    check_if_dm,
)

logger = structlog.get_logger(__name__)


def register_queue_2v2_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="queue2v2", description="Join the 2v2 ranked matchmaking queue")
    @app_commands.check(check_if_accepted_tos)
    @app_commands.check(check_if_completed_setup)
    @app_commands.check(check_if_banned)
    @app_commands.check(check_if_dm)
    async def queue_2v2_command(interaction: discord.Interaction) -> None:
        logger.debug(f"queue_2v2_command invoked by user={interaction.user.id}")
        await interaction.response.defer()

        leader_race: str | None = None
        member_race: str | None = None
        map_vetoes: list[str] = []

        try:
            async with get_session().get(
                f"{BACKEND_URL}/preferences_2v2/{interaction.user.id}"
            ) as resp:
                data = await resp.json()
                prefs = data.get("preferences")
                if prefs:
                    # Restore leader/member races from whichever composition was saved
                    if prefs.get("last_pure_bw_leader_race"):
                        leader_race = prefs["last_pure_bw_leader_race"]
                        member_race = prefs.get("last_pure_bw_member_race")
                    elif prefs.get("last_pure_sc2_leader_race"):
                        leader_race = prefs["last_pure_sc2_leader_race"]
                        member_race = prefs.get("last_pure_sc2_member_race")
                    elif prefs.get("last_mixed_leader_race"):
                        leader_race = prefs["last_mixed_leader_race"]
                        member_race = prefs.get("last_mixed_member_race")
                    map_vetoes = prefs.get("last_chosen_vetoes") or []
        except Exception:
            logger.warning("Failed to load 2v2 preferences", exc_info=True)

        locale = get_player_locale(interaction.user.id)
        embed = QueueSetupEmbed2v2(leader_race, member_race, map_vetoes, locale=locale)
        view = QueueSetupView2v2(
            discord_user_id=interaction.user.id,
            leader_race=leader_race,
            member_race=member_race,
            map_vetoes=map_vetoes,
        )
        await interaction.followup.send(embed=embed, view=view)
