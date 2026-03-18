import structlog
import discord
from discord import app_commands

from bot.core.config import BACKEND_URL
from bot.core.http import get_session
from common.datetime_helpers import to_discord_timestamp
from bot.helpers.checks import check_if_banned, check_if_dm
from bot.helpers.emotes import (
    get_flag_emote,
    get_game_emote,
    get_globe_emote,
    get_race_emote,
)
from bot.helpers.i18n import LOCALE_DISPLAY_NAMES
from common.lookups.country_lookups import get_country_by_code
from common.lookups.race_lookups import get_race_by_code
from common.lookups.region_lookups import get_geographic_region_by_code

logger = structlog.get_logger(__name__)

# ----------
# Components
# ----------

# --- Embeds ---


class ProfileNotFoundEmbed(discord.Embed):
    def __init__(self) -> None:
        super().__init__(
            title="❌ Profile Not Found",
            description="No profile found. Use `/setup` to create your player profile.",
            color=discord.Color.red(),
        )


class ProfileEmbed(discord.Embed):
    def __init__(
        self, user: discord.User | discord.Member, player: dict, mmrs: list[dict]
    ) -> None:
        completed = player.get("completed_setup", False)
        color = discord.Color.green() if completed else discord.Color.orange()
        status_icon = "✅" if completed else "⚠️"
        title_name = player.get("player_name") or user.name

        super().__init__(
            title=f"{status_icon} Player Profile: {title_name}",
            color=color,
        )

        if user.display_avatar:
            self.set_thumbnail(url=user.display_avatar.url)

        self._add_basic_info(player)
        self._add_location(player)
        self._add_mmrs(mmrs)
        self._add_account_status(player)

        self.set_footer(text=f"Discord: {user.name} • ID: {user.id}")

    def _add_basic_info(self, player: dict) -> None:
        parts = [
            f"- **Player Name:** {player.get('player_name') or 'Not set'}",
            f"- **BattleTag:** {player.get('battletag') or 'Not set'}",
        ]
        alt_ids: list[str] = player.get("alt_player_names") or []
        if alt_ids:
            parts.append(f"- **Alt IDs:** {', '.join(alt_ids)}")
        self.add_field(
            name="📋 Basic Information", value="\n".join(parts), inline=False
        )

    def _add_location(self, player: dict) -> None:
        parts: list[str] = []

        nationality = player.get("nationality")
        if nationality:
            country = get_country_by_code(nationality)
            if country:
                flag = get_flag_emote(nationality)
                parts.append(f"- **Nationality:** {flag} {country['name']}")

        location = player.get("location")
        if location:
            region = get_geographic_region_by_code(location)
            if region:
                globe = get_globe_emote(region["globe_emote_code"])
                parts.append(f"- **Location:** {globe} {region['name']}")

        language = player.get("language")
        if language:
            entry = LOCALE_DISPLAY_NAMES.get(language)
            if entry:
                parts.append(f"- **Language:** {entry[1]} {entry[0]}")
            else:
                parts.append(f"- **Language:** {language}")

        if parts:
            self.add_field(name="📍 Location", value="\n".join(parts), inline=False)

    def _add_mmrs(self, mmrs: list[dict]) -> None:
        if not mmrs:
            self.add_field(
                name="🎮 MMR",
                value="No ranked games played yet.",
                inline=False,
            )
            return

        bw_mmrs = [m for m in mmrs if m.get("race", "").startswith("bw_")]
        sc2_mmrs = [m for m in mmrs if m.get("race", "").startswith("sc2_")]

        if bw_mmrs:
            self.add_field(
                name=f"{get_game_emote('bw')} Brood War MMR",
                value=_format_mmr_rows(bw_mmrs),
                inline=False,
            )
        if sc2_mmrs:
            self.add_field(
                name=f"{get_game_emote('sc2')} StarCraft II MMR",
                value=_format_mmr_rows(sc2_mmrs),
                inline=False,
            )

    def _add_account_status(self, player: dict) -> None:
        tos = player.get("accepted_tos", False)
        setup = player.get("completed_setup", False)
        parts = [
            f"{'✅' if tos else '❌'} Terms of Service {'accepted' if tos else 'not accepted'}",
            f"{'✅' if setup else '⚠️'} Setup {'completed' if setup else 'incomplete'}",
        ]
        self.add_field(name="📊 Account Status", value="\n".join(parts), inline=False)


# ----------------
# Internal helpers
# ----------------


def _format_mmr_rows(mmrs: list[dict]) -> str:
    lines: list[str] = []
    for m in mmrs:
        race_code: str = m.get("race") or ""
        race = get_race_by_code(race_code)
        race_name = race["name"] if race else race_code

        try:
            race_emote = get_race_emote(race_code)
        except ValueError:
            race_emote = "🎮"

        gp: int = m.get("games_played") or 0
        gw: int = m.get("games_won") or 0
        gl: int = m.get("games_lost") or 0
        gd: int = m.get("games_drawn") or 0
        mmr_val: int = m.get("mmr") or 0
        wr = (gw / gp * 100) if gp > 0 else 0.0

        line = f"- {race_emote} **{race_name}:** {mmr_val} MMR • {gw}W-{gl}L-{gd}D ({wr:.1f}%)"

        last_played = m.get("last_played_at")
        if last_played and gp > 0:
            ts = to_discord_timestamp(raw=last_played, style="f")
            if ts != "—":
                line += f"\n  - **Last Played:** {ts}"

        lines.append(line)
    return "\n".join(lines)


async def _fetch_profile(discord_uid: int) -> tuple[dict | None, list[dict]]:
    async with get_session().get(f"{BACKEND_URL}/profile/{discord_uid}") as response:
        data = await response.json()
    return data.get("player"), data.get("mmrs_1v1") or []


# --------------------
# Command registration
# --------------------


def register_profile_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="profile", description="View your player profile")
    @app_commands.check(check_if_banned)
    @app_commands.check(check_if_dm)
    async def profile_command(interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        discord_uid = interaction.user.id
        logger.info(f"profile_command invoked by user={discord_uid}")

        player, mmrs = await _fetch_profile(discord_uid)

        if player is None:
            await interaction.followup.send(embed=ProfileNotFoundEmbed())
            return

        logger.info(
            f"profile_command: found player={player.get('player_name')!r} "
            f"mmrs={len(mmrs)} for user={discord_uid}"
        )
        await interaction.followup.send(
            embed=ProfileEmbed(interaction.user, player, mmrs)
        )
