import structlog
import discord
from discord import app_commands

from bot.components.embeds import ErrorEmbed, QueueSetupEmbed1v1, QueueSetupEmbed2v2
from bot.components.views import (
    MatchFoundView1v1,
    MatchReportView1v1,
    QueueSetupView1v1,
    QueueSetupView2v2,
)
from bot.core.config import BACKEND_URL, GAME_MODE_CHOICES
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from common.i18n import t
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
    @tree.command(name="queue", description="Join the ranked matchmaking queue")
    @app_commands.check(check_if_accepted_tos)
    @app_commands.check(check_if_completed_setup)
    @app_commands.check(check_if_queueing)
    @app_commands.check(check_if_banned)
    @app_commands.check(check_if_dm)
    @app_commands.choices(game_mode=GAME_MODE_CHOICES)
    async def queue_command(
        interaction: discord.Interaction,
        game_mode: app_commands.Choice[str] | None = None,
    ) -> None:
        mode = game_mode.value if game_mode else "1v1"
        logger.debug(
            f"queue_command invoked by user={interaction.user.id}, mode={mode}"
        )
        await interaction.response.defer()

        if mode == "2v2":
            await _queue_2v2(interaction)
        else:
            await _queue_1v1(interaction)


async def _queue_1v1(interaction: discord.Interaction) -> None:
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
                bw_race = next((r for r in saved_races if r.startswith("bw_")), None)
                sc2_race = next((r for r in saved_races if r.startswith("sc2_")), None)
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


async def _queue_2v2(interaction: discord.Interaction) -> None:
    uid = interaction.user.id
    locale = get_player_locale(uid)

    # Gate: player must be in a party.
    try:
        async with get_session().get(f"{BACKEND_URL}/party_2v2/{uid}") as resp:
            party_data = await resp.json()
    except Exception:
        await interaction.followup.send(
            embed=ErrorEmbed(
                title=t("error_embed.title.generic", locale),
                description=t("error.backend_unavailable", locale),
                locale=locale,
            )
        )
        return

    if not party_data.get("in_party"):
        await interaction.followup.send(
            embed=ErrorEmbed(
                title=t("error_embed.title.generic", locale),
                description=t("error.queue_not_in_party", locale),
                locale=locale,
            )
        )
        return

    leader_player_name: str = party_data.get("leader_player_name", "Leader")
    member_player_name: str = party_data.get("member_player_name", "Member")

    # Load saved 2v2 preferences.
    pure_bw_leader: str | None = None
    pure_bw_member: str | None = None
    mixed_leader: str | None = None
    mixed_member: str | None = None
    pure_sc2_leader: str | None = None
    pure_sc2_member: str | None = None
    map_vetoes: list[str] = []

    try:
        async with get_session().get(f"{BACKEND_URL}/preferences_2v2/{uid}") as resp:
            data = await resp.json()
            prefs = data.get("preferences")
            if prefs:
                pure_bw_leader = prefs.get("last_pure_bw_leader_race")
                pure_bw_member = prefs.get("last_pure_bw_member_race")
                mixed_leader = prefs.get("last_mixed_leader_race")
                mixed_member = prefs.get("last_mixed_member_race")
                pure_sc2_leader = prefs.get("last_pure_sc2_leader_race")
                pure_sc2_member = prefs.get("last_pure_sc2_member_race")
                map_vetoes = prefs.get("last_chosen_vetoes") or []
    except Exception:
        logger.warning("Failed to load 2v2 preferences", exc_info=True)

    embed = QueueSetupEmbed2v2(
        pure_bw_leader,
        pure_bw_member,
        mixed_leader,
        mixed_member,
        pure_sc2_leader,
        pure_sc2_member,
        map_vetoes,
        leader_player_name=leader_player_name,
        member_player_name=member_player_name,
        locale=locale,
    )
    view = QueueSetupView2v2(
        discord_user_id=uid,
        pure_bw_leader_race=pure_bw_leader,
        pure_bw_member_race=pure_bw_member,
        mixed_leader_race=mixed_leader,
        mixed_member_race=mixed_member,
        pure_sc2_leader_race=pure_sc2_leader,
        pure_sc2_member_race=pure_sc2_member,
        map_vetoes=map_vetoes,
        leader_player_name=leader_player_name,
        member_player_name=member_player_name,
    )
    await interaction.followup.send(embed=embed, view=view)
