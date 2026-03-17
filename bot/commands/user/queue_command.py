import time
from typing import Any

import structlog

import discord
from discord import app_commands

from bot.core.config import BACKEND_URL
from bot.core.http import get_session
from bot.helpers.checks import check_if_dm
from bot.helpers.emotes import (
    get_flag_emote,
    get_game_emote,
    get_race_emote,
    get_rank_emote,
)
from common.lookups.map_lookups import get_map_by_short_name, get_maps
from common.lookups.mod_lookups import get_mod_by_code
from common.lookups.race_lookups import get_races
from common.lookups.region_lookups import (
    get_game_region_by_code,
    get_game_server_by_code,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BW_RACES = ["bw_terran", "bw_zerg", "bw_protoss"]
_SC2_RACES = ["sc2_terran", "sc2_zerg", "sc2_protoss"]
_MAX_MAP_VETOES = 4
_QUICKSTART_URL = "https://rentry.co/evoladderbot-quickstartguide"
_NUMBER_EMOTES = [":one:", ":two:", ":three:", ":four:"]

# Game settings (match the alpha defaults)
_EXPECTED_GAME_PRIVACY = "Normal"
_EXPECTED_GAME_SPEED = "Faster"
_EXPECTED_GAME_DURATION = "Infinite"
_EXPECTED_LOCKED_ALLIANCES = "Yes"

# ---------------------------------------------------------------------------
# Replay validation gate
# ---------------------------------------------------------------------------
# When True, the match-report dropdown is locked until a replay has been
# uploaded AND its race check passes.  The verification results are always
# shown in the ReplayDetailsEmbed regardless of this flag; the flag only
# controls whether those results actually gate reporting.
_ENABLE_REPLAY_VALIDATION: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _race_display(race_code: str) -> str:
    races = get_races()
    race = races.get(race_code)
    return race["name"] if race else race_code


def _race_group_label(race_code: str) -> str:
    if race_code.startswith("bw_"):
        return "Brood War"
    return "StarCraft II"


def _get_map_game(map_name: str) -> str:
    """Return 'bw' or 'sc2' for a map by looking it up in the map pool."""
    maps = get_maps(game_mode="1v1", season="season_alpha") or {}
    map_data = maps.get(map_name)
    if map_data:
        return map_data.get("game", "sc2")
    return "sc2"


def _report_display(report: str) -> str:
    mapping = {
        "player_1_win": "Player 1 Win",
        "player_2_win": "Player 2 Win",
        "draw": "Draw",
        "abort": "Aborted",
        "abandoned": "Abandoned",
        "invalidated": "Invalidated (Conflicting Reports)",
    }
    return mapping.get(report, report)


def _server_display(server_code: str) -> str:
    """Format server code to 'Server Name (Region Name)' like the alpha."""
    server = get_game_server_by_code(server_code)
    if not server:
        return server_code
    region = get_game_region_by_code(server["game_region_code"])
    region_name = region["name"] if region else server["game_region_code"]
    return f"{server['name']} ({region_name})"


def _get_map_link(map_name: str, server_code: str) -> str:
    """Get the appropriate battlenet map link based on server region."""
    map_data = get_map_by_short_name(map_name)
    if not map_data:
        return "Unavailable"
    server = get_game_server_by_code(server_code)
    game_region_code = server["game_region_code"] if server else "AM"
    region = get_game_region_by_code(game_region_code)
    region_code = region["code"] if region else game_region_code
    link_key = {"AM": "am_link", "EU": "eu_link", "AS": "as_link"}.get(
        region_code, "am_link"
    )
    return str(map_data.get(link_key, "Unavailable") or "Unavailable")


def _get_mod_link(server_code: str) -> str:
    """Get the appropriate battlenet mod link based on server region."""
    mod = get_mod_by_code("multi")
    if not mod:
        return "Unavailable"
    server = get_game_server_by_code(server_code)
    region_code = server["game_region_code"] if server else "AM"
    link_key = {"AM": "am_link", "EU": "eu_link", "AS": "as_link"}.get(
        region_code, "am_link"
    )
    return str(mod.get(link_key, "Unavailable") or "Unavailable")


async def _fetch_player_info(discord_uid: int) -> dict[str, Any] | None:
    """Fetch player info from the backend API."""
    try:
        async with get_session().get(f"{BACKEND_URL}/players/{discord_uid}") as resp:
            data = await resp.json()
            player: dict[str, Any] | None = data.get("player")
            return player
    except Exception:
        logger.warning("Failed to fetch player info", discord_uid=discord_uid)
        return None


# ---------------------------------------------------------------------------
# Embeds
# ---------------------------------------------------------------------------


def build_queue_setup_embed(
    bw_race: str | None,
    sc2_race: str | None,
    map_vetoes: list[str],
) -> discord.Embed:
    """Build the queue setup embed matching the alpha UI."""
    embed = discord.Embed(
        title="🎮 Matchmaking Queue",
        color=discord.Color.blue(),
    )

    # Quick start guide warning
    embed.add_field(
        name="⚠️ NEW PLAYERS START HERE ⚠️",
        value=f"📘 **QUICK START GUIDE:**  [READ THIS BEFORE YOUR FIRST MATCH!]({_QUICKSTART_URL})\n",
        inline=False,
    )

    # Selected races
    race_lines: list[str] = []
    if bw_race:
        race_lines.append(
            f"- Brood War: {get_race_emote(bw_race)} {_race_display(bw_race)}"
        )
    if sc2_race:
        race_lines.append(
            f"- StarCraft II: {get_race_emote(sc2_race)} {_race_display(sc2_race)}"
        )
    race_value = "\n".join(race_lines) if race_lines else "None selected"
    embed.add_field(name="Selected Races", value=race_value, inline=False)

    # Vetoed maps
    veto_count = len(map_vetoes)
    if map_vetoes:
        sorted_vetoes = sorted(map_vetoes)
        veto_lines: list[str] = []
        for i, map_name in enumerate(sorted_vetoes):
            game = _get_map_game(map_name)
            game_emote = get_game_emote(game)
            veto_lines.append(f"{_NUMBER_EMOTES[i]} {game_emote} {map_name}")
        veto_value = "\n".join(veto_lines)
    else:
        veto_value = "No vetoes"
    embed.add_field(
        name=f"Vetoed Maps ({veto_count}/{_MAX_MAP_VETOES})",
        value=veto_value,
        inline=False,
    )

    return embed


class QueueSearchingEmbed(discord.Embed):
    def __init__(self, stats: dict | None = None, *, match_found: bool = False) -> None:
        bw_only = stats.get("bw_only", 0) if stats else 0
        sc2_only = stats.get("sc2_only", 0) if stats else 0
        both = stats.get("both", 0) if stats else 0
        now = time.time()
        next_search = int((now // 60 + 1) * 60)

        if match_found:
            description = (
                "The queue is searching for a game.\n\n- Search interval: 60 seconds"
            )
        else:
            description = (
                "The queue is searching for a game.\n\n"
                f"- Next search: <t:{next_search}:R>\n"
                "- Search interval: 60 seconds\n"
                "- Current players queueing:\n"
                f"  - Brood War: {bw_only}\n"
                f"  - StarCraft II: {sc2_only}\n"
                f"  - Both: {both}"
            )

        super().__init__(
            title="🔍 Searching...",
            description=description,
            color=discord.Color.blue(),
        )

        if match_found:
            self.add_field(
                name="✅ Match Found!",
                value=(
                    "You have been removed from the queue. "
                    "Check your DMs for match confirmation details."
                ),
                inline=False,
            )


class QueueErrorEmbed(discord.Embed):
    def __init__(self, error: str) -> None:
        super().__init__(
            title="Queue Error",
            description=error,
            color=discord.Color.red(),
        )


class MatchFoundEmbed(discord.Embed):
    def __init__(self, match_data: dict) -> None:
        match_id = match_data.get("id", "?")
        super().__init__(
            title=f"⚔️ Match #{match_id} Found!",
            description=(
                "A match has been found for you.\n\n"
                "Press **Confirm Match** to proceed, or **Abort Match** to cancel.\n"
                "Full match details will be shown once **both** players confirm."
            ),
            color=discord.Color.green(),
        )


class MatchWaitingConfirmEmbed(discord.Embed):
    def __init__(self, match_id: int) -> None:
        super().__init__(
            title=f"✅ Match #{match_id} Confirmed!",
            description="Both players confirmed. Match details are now available below.",
            color=discord.Color.green(),
        )


class MatchInfoEmbed(discord.Embed):
    """Full match details embed matching the alpha UI layout."""

    def __init__(
        self,
        match_data: dict,
        p1_info: dict[str, Any] | None = None,
        p2_info: dict[str, Any] | None = None,
        pending_report: str | None = None,
        replay_uploaded: bool = False,
    ) -> None:
        match_id = match_data.get("id", "?")
        p1_name = match_data.get("player_1_name", "Player 1")
        p2_name = match_data.get("player_2_name", "Player 2")
        p1_race = match_data.get("player_1_race", "")
        p2_race = match_data.get("player_2_race", "")
        p1_mmr = match_data.get("player_1_mmr", "?")
        p2_mmr = match_data.get("player_2_mmr", "?")
        p1_uid = match_data.get("player_1_discord_uid")
        p2_uid = match_data.get("player_2_discord_uid")
        map_name = match_data.get("map_name", "Unknown")
        server_code = match_data.get("server_name", "Unknown")

        # Resolve display details
        p1_country = (p1_info.get("nationality") or "XX") if p1_info else "XX"
        p2_country = (p2_info.get("nationality") or "XX") if p2_info else "XX"
        p1_flag = get_flag_emote(p1_country)
        p2_flag = get_flag_emote(p2_country)

        # Rank — not yet implemented in beta, use "U" (unranked) placeholder
        p1_rank_emote = get_rank_emote("U")
        p2_rank_emote = get_rank_emote("U")

        p1_race_emote = get_race_emote(p1_race) if p1_race else ""
        p2_race_emote = get_race_emote(p2_race) if p2_race else ""

        # Title: rank flag race name (MMR) vs rank flag race name (MMR)
        title = (
            f"Match #{match_id}:\n"
            f"{p1_rank_emote} {p1_flag} {p1_race_emote} {p1_name} ({p1_mmr}) "
            f"vs "
            f"{p2_rank_emote} {p2_flag} {p2_race_emote} {p2_name} ({p2_mmr})"
        )

        super().__init__(title=title, description="", color=discord.Color.teal())

        # Spacer
        self.add_field(name="", value="", inline=False)

        # --- Player and Contact Information ---
        p1_race_name = _race_display(p1_race) if p1_race else "Unknown"
        p2_race_name = _race_display(p2_race) if p2_race else "Unknown"

        p1_discord_username = (
            p1_info.get("discord_username", "Unknown") if p1_info else "Unknown"
        )
        p2_discord_username = (
            p2_info.get("discord_username", "Unknown") if p2_info else "Unknown"
        )

        p1_battletag = (p1_info.get("battletag") or None) if p1_info else None
        p2_battletag = (p2_info.get("battletag") or None) if p2_info else None

        p1_alts = (p1_info.get("alt_player_names") or []) if p1_info else []
        p2_alts = (p2_info.get("alt_player_names") or []) if p2_info else []

        p1_line = (
            f"- {p1_rank_emote} {p1_flag} {p1_race_emote} {p1_name} ({p1_race_name})"
        )
        p1_line += f"\n  - Discord: {p1_discord_username} ({p1_uid})"
        if p1_battletag:
            p1_line += f"\n  - BattleTag: `{p1_battletag}`"
        if p1_alts:
            p1_line += f"\n  - (a.k.a. {', '.join(p1_alts)})"

        p2_line = (
            f"- {p2_rank_emote} {p2_flag} {p2_race_emote} {p2_name} ({p2_race_name})"
        )
        p2_line += f"\n  - Discord: {p2_discord_username} ({p2_uid})"
        if p2_battletag:
            p2_line += f"\n  - BattleTag: `{p2_battletag}`"
        if p2_alts:
            p2_line += f"\n  - (a.k.a. {', '.join(p2_alts)})"

        self.add_field(
            name="**👥 Player and Contact Information:**",
            value=f"{p1_line}\n{p2_line}",
            inline=False,
        )

        # Spacer
        self.add_field(name="", value="", inline=False)

        # --- Map and Mod Information ---
        map_info = get_map_by_short_name(map_name)
        map_author = map_info["author"] if map_info else "Unknown"
        map_link = _get_map_link(map_name, server_code)

        mod = get_mod_by_code("multi")
        mod_name = mod["name"] if mod else "SC: Evo Complete"
        mod_author = mod["author"] if mod else "SCEvoDev"
        mod_link = _get_mod_link(server_code)

        server_full = _server_display(server_code)

        self.add_field(
            name="**🗺️ Map and Mod Information:**",
            value=(
                f"- Map: `{map_info['name'] if map_info else map_name}`\n"
                f"  - Map Link: `{map_link}`\n"
                f"  - Author: `{map_author}`\n"
                f"- Mod: `{mod_name}`\n"
                f"  - Mod Link: `{mod_link}`\n"
                f"  - Author: `{mod_author}`"
            ),
            inline=False,
        )

        # Spacer
        self.add_field(name="", value="", inline=False)

        # --- Match Settings ---
        self.add_field(
            name="🔧 Match Settings:",
            value=(
                f"- Server: `{server_full}`\n"
                f"- In-Game Channel: `SCEvoLadder`\n"
                f"- Locked Alliances: `{_EXPECTED_LOCKED_ALLIANCES}`"
            ),
            inline=True,
        )

        self.add_field(
            name="\u3164",
            value=(
                f"- Game Privacy: `{_EXPECTED_GAME_PRIVACY}`\n"
                f"- Game Speed: `{_EXPECTED_GAME_SPEED}`\n"
                f"- Game Duration: `{_EXPECTED_GAME_DURATION}`"
            ),
            inline=True,
        )

        # Spacer
        self.add_field(name="", value="", inline=False)
        self.add_field(name="", value="", inline=False)

        # --- Match Result ---
        if pending_report is not None:
            result_value = (
                f"- Result: `{_report_display(pending_report)}` ✅\n"
                "- Waiting for opponent to report..."
            )
        else:
            result_value = "- Result: `Not selected`"
        self.add_field(
            name="**🏆 Match Result:**",
            value=result_value,
            inline=True,
        )

        # --- Replay Status ---
        replay_value = (
            "- Replay Uploaded: `Yes`"
            if replay_uploaded
            else "- Replay Uploaded: `No`\n- Replay Uploaded At: `N/A`"
        )
        self.add_field(
            name="**📡 Replay Status:**",
            value=replay_value,
            inline=True,
        )

        # Footer instruction
        if _ENABLE_REPLAY_VALIDATION and not replay_uploaded:
            footer_text = (
                "ℹ️ To report the match result, upload a replay. "
                "The dropdown menus below will unlock once a valid replay is uploaded."
            )
        else:
            footer_text = "ℹ️ Report the match result using the dropdown menus below."
        self.set_footer(text=footer_text)


def _player_header(
    rank_emote: str | discord.PartialEmoji,
    flag_emote: str | discord.PartialEmoji,
    race_emote: str | discord.PartialEmoji,
    name: str,
    mmr: int | str,
    new_mmr: int | str | None = None,
) -> str:
    """Return '{rank} {flag} {race} {name} ({mmr})' or '({mmr}→{new_mmr})'."""
    mmr_part = f"({mmr} → {new_mmr})" if new_mmr is not None else f"({mmr})"
    return f"{rank_emote} {flag_emote} {race_emote} **{name} {mmr_part}**"


class MatchAbortedEmbed(discord.Embed):
    def __init__(
        self,
        match_data: dict,
        p1_info: dict[str, Any] | None = None,
        p2_info: dict[str, Any] | None = None,
    ) -> None:
        match_id = match_data.get("id", "?")
        p1_name = match_data.get("player_1_name", "Player 1")
        p2_name = match_data.get("player_2_name", "Player 2")
        p1_race = match_data.get("player_1_race", "")
        p2_race = match_data.get("player_2_race", "")
        p1_mmr = match_data.get("player_1_mmr", "?")
        p2_mmr = match_data.get("player_2_mmr", "?")

        p1_country = (p1_info.get("nationality") or "XX") if p1_info else "XX"
        p2_country = (p2_info.get("nationality") or "XX") if p2_info else "XX"

        p1_hdr = _player_header(
            get_rank_emote("U"),
            get_flag_emote(p1_country),
            get_race_emote(p1_race) if p1_race else "",
            p1_name,
            p1_mmr,
        )
        p2_hdr = _player_header(
            get_rank_emote("U"),
            get_flag_emote(p2_country),
            get_race_emote(p2_race) if p2_race else "",
            p2_name,
            p2_mmr,
        )

        # Determine who aborted
        if match_data.get("player_1_report") == "abort":
            aborter = p1_name
        else:
            aborter = p2_name

        super().__init__(
            title=f"🛑 Match #{match_id} Aborted",
            description=f"{p1_hdr} vs {p2_hdr}",
            color=discord.Color.red(),
        )
        self.add_field(
            name="**MMR Changes:**",
            value=f"• {p1_name}: `+0 ({p1_mmr})`\n• {p2_name}: `+0 ({p2_mmr})`",
            inline=False,
        )
        self.add_field(
            name="**Reason:**",
            value=f"The match was aborted by **{aborter}**. No MMR changes were applied.",
            inline=False,
        )


class MatchAbandonedEmbed(discord.Embed):
    def __init__(
        self,
        match_data: dict,
        p1_info: dict[str, Any] | None = None,
        p2_info: dict[str, Any] | None = None,
    ) -> None:
        match_id = match_data.get("id", "?")
        p1_name = match_data.get("player_1_name", "Player 1")
        p2_name = match_data.get("player_2_name", "Player 2")
        p1_race = match_data.get("player_1_race", "")
        p2_race = match_data.get("player_2_race", "")
        p1_mmr = match_data.get("player_1_mmr", "?")
        p2_mmr = match_data.get("player_2_mmr", "?")

        p1_country = (p1_info.get("nationality") or "XX") if p1_info else "XX"
        p2_country = (p2_info.get("nationality") or "XX") if p2_info else "XX"

        p1_hdr = _player_header(
            get_rank_emote("U"),
            get_flag_emote(p1_country),
            get_race_emote(p1_race) if p1_race else "",
            p1_name,
            p1_mmr,
        )
        p2_hdr = _player_header(
            get_rank_emote("U"),
            get_flag_emote(p2_country),
            get_race_emote(p2_race) if p2_race else "",
            p2_name,
            p2_mmr,
        )

        # Determine who failed to confirm (has "abandoned" as their report)
        if match_data.get("player_1_report") == "abandoned":
            abandoner = p1_name
        else:
            abandoner = p2_name

        super().__init__(
            title=f"🛑 Match #{match_id} Abandoned",
            description=f"{p1_hdr} vs {p2_hdr}",
            color=discord.Color.red(),
        )
        self.add_field(
            name="**MMR Changes:**",
            value=f"• {p1_name}: `+0 ({p1_mmr})`\n• {p2_name}: `+0 ({p2_mmr})`",
            inline=False,
        )
        self.add_field(
            name="**Reason:**",
            value=(
                f"The match was automatically abandoned because **{abandoner}** "
                "did not confirm in time."
            ),
            inline=False,
        )


class MatchFinalizedEmbed(discord.Embed):
    def __init__(
        self,
        match_data: dict,
        p1_info: dict[str, Any] | None = None,
        p2_info: dict[str, Any] | None = None,
    ) -> None:
        match_id = match_data.get("id", "?")
        result = match_data.get("match_result", "unknown")
        p1_name = match_data.get("player_1_name", "Player 1")
        p2_name = match_data.get("player_2_name", "Player 2")
        p1_race = match_data.get("player_1_race", "")
        p2_race = match_data.get("player_2_race", "")
        p1_mmr = match_data.get("player_1_mmr", 0)
        p2_mmr = match_data.get("player_2_mmr", 0)
        p1_change = match_data.get("player_1_mmr_change") or 0
        p2_change = match_data.get("player_2_mmr_change") or 0
        p1_new = p1_mmr + p1_change
        p2_new = p2_mmr + p2_change

        p1_country = (p1_info.get("nationality") or "XX") if p1_info else "XX"
        p2_country = (p2_info.get("nationality") or "XX") if p2_info else "XX"
        p1_rank = get_rank_emote("U")
        p2_rank = get_rank_emote("U")
        p1_flag = get_flag_emote(p1_country)
        p2_flag = get_flag_emote(p2_country)
        p1_race_emote = get_race_emote(p1_race) if p1_race else ""
        p2_race_emote = get_race_emote(p2_race) if p2_race else ""

        p1_hdr = _player_header(
            p1_rank, p1_flag, p1_race_emote, p1_name, p1_mmr, p1_new
        )
        p2_hdr = _player_header(
            p2_rank, p2_flag, p2_race_emote, p2_name, p2_mmr, p2_new
        )

        super().__init__(
            title=f"🏆 Match #{match_id} Result Finalized",
            description=f"{p1_hdr} vs {p2_hdr}",
            color=discord.Color.gold(),
        )

        # Result field
        if result == "draw":
            result_value = "⚖️ **Draw**"
        elif result == "player_1_win":
            result_value = f"🏆 {p1_rank} {p1_flag} {p1_race_emote} {p1_name}"
        else:
            result_value = f"🏆 {p2_rank} {p2_flag} {p2_race_emote} {p2_name}"

        p1_sign = "+" if p1_change >= 0 else ""
        p2_sign = "+" if p2_change >= 0 else ""

        self.add_field(name="**Result:**", value=result_value, inline=True)
        self.add_field(
            name="**MMR Changes:**",
            value=(
                f"- {p1_name}: `{p1_sign}{p1_change} ({p1_mmr} → {p1_new})`\n"
                f"- {p2_name}: `{p2_sign}{p2_change} ({p2_mmr} → {p2_new})`"
            ),
            inline=True,
        )


class MatchConflictEmbed(discord.Embed):
    def __init__(
        self,
        match_data: dict,
        p1_info: dict[str, Any] | None = None,
        p2_info: dict[str, Any] | None = None,
    ) -> None:
        match_id = match_data.get("id", "?")
        p1_name = match_data.get("player_1_name", "Player 1")
        p2_name = match_data.get("player_2_name", "Player 2")
        p1_race = match_data.get("player_1_race", "")
        p2_race = match_data.get("player_2_race", "")
        p1_mmr = match_data.get("player_1_mmr", "?")
        p2_mmr = match_data.get("player_2_mmr", "?")

        p1_country = (p1_info.get("nationality") or "XX") if p1_info else "XX"
        p2_country = (p2_info.get("nationality") or "XX") if p2_info else "XX"

        p1_hdr = _player_header(
            get_rank_emote("U"),
            get_flag_emote(p1_country),
            get_race_emote(p1_race) if p1_race else "",
            p1_name,
            p1_mmr,
        )
        p2_hdr = _player_header(
            get_rank_emote("U"),
            get_flag_emote(p2_country),
            get_race_emote(p2_race) if p2_race else "",
            p2_name,
            p2_mmr,
        )

        p1_report = match_data.get("player_1_report", "?")
        p2_report = match_data.get("player_2_report", "?")

        super().__init__(
            title=f"⚠️ Match #{match_id} — Conflicting Reports",
            description=f"{p1_hdr} vs {p2_hdr}",
            color=discord.Color.orange(),
        )
        self.add_field(
            name="**Reports:**",
            value=(
                f"- {p1_name}: `{_report_display(p1_report)}`\n"
                f"- {p2_name}: `{_report_display(p2_report)}`"
            ),
            inline=False,
        )
        self.add_field(
            name="**Reason:**",
            value=(
                "Both players submitted conflicting reports. "
                "The match result has been marked as **conflict** and no MMR changes were applied. "
                "Please contact an admin to resolve this."
            ),
            inline=False,
        )


# ---------------------------------------------------------------------------
# Selects
# ---------------------------------------------------------------------------


class BwRaceSelect(discord.ui.Select):
    def __init__(self, selected: str | None = None) -> None:
        races = get_races()
        options = [
            discord.SelectOption(
                label=races[code]["name"],
                value=code,
                emoji=get_race_emote(code),
                default=(code == selected),
            )
            for code in _BW_RACES
            if code in races
        ]
        super().__init__(
            placeholder="Select your Brood War race (max 1)",
            min_values=0,
            max_values=1,
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: QueueSetupView = self.view  # type: ignore[assignment]
        view.bw_race = self.values[0] if self.values else None
        await view.persist_and_refresh(interaction)


class Sc2RaceSelect(discord.ui.Select):
    def __init__(self, selected: str | None = None) -> None:
        races = get_races()
        options = [
            discord.SelectOption(
                label=races[code]["name"],
                value=code,
                emoji=get_race_emote(code),
                default=(code == selected),
            )
            for code in _SC2_RACES
            if code in races
        ]
        super().__init__(
            placeholder="Select your StarCraft II race (max 1)",
            min_values=0,
            max_values=1,
            options=options,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: QueueSetupView = self.view  # type: ignore[assignment]
        view.sc2_race = self.values[0] if self.values else None
        await view.persist_and_refresh(interaction)


class MapVetoSelect(discord.ui.Select):
    def __init__(self, selected: list[str] | None = None) -> None:
        maps = get_maps(game_mode="1v1", season="season_alpha") or {}
        options = [
            discord.SelectOption(
                label=map_data["short_name"],
                value=map_name,
                emoji=get_game_emote(map_data.get("game", "sc2")),
                default=(map_name in (selected or [])),
            )
            for map_name, map_data in sorted(maps.items())
        ]
        if not options:
            options = [discord.SelectOption(label="No maps available", value="none")]

        super().__init__(
            placeholder=f"Select maps to veto (max {_MAX_MAP_VETOES})...",
            min_values=0,
            max_values=min(_MAX_MAP_VETOES, len(options)),
            options=options,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: QueueSetupView = self.view  # type: ignore[assignment]
        view.map_vetoes = [v for v in self.values if v != "none"]
        await view.persist_and_refresh(interaction)


class MatchReportSelect(discord.ui.Select):
    def __init__(self, match_id: int, p1_name: str, p2_name: str) -> None:
        self.match_id = match_id
        options = [
            discord.SelectOption(label=f"{p1_name} victory", value="player_1_win"),
            discord.SelectOption(label=f"{p2_name} victory", value="player_2_win"),
            discord.SelectOption(label="Draw", value="draw"),
        ]
        super().__init__(
            placeholder="Report match result...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: MatchReportView = self.view  # type: ignore[assignment]
        report = self.values[0]
        await view.submit_report(interaction, report)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class QueueSetupView(discord.ui.View):
    def __init__(
        self,
        discord_user_id: int,
        bw_race: str | None = None,
        sc2_race: str | None = None,
        map_vetoes: list[str] | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self.discord_user_id = discord_user_id
        self.bw_race = bw_race
        self.sc2_race = sc2_race
        self.map_vetoes = map_vetoes or []
        self._build()

    def _build(self) -> None:
        self.clear_items()

        # Row 0: buttons
        async def on_join(interaction: discord.Interaction) -> None:
            await _join_queue(
                interaction,
                self.discord_user_id,
                self.bw_race,
                self.sc2_race,
                self.map_vetoes,
            )

        join_btn: discord.ui.Button[QueueSetupView] = discord.ui.Button(
            label="Join Queue",
            emoji="🚀",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        join_btn.callback = on_join  # type: ignore[method-assign]
        self.add_item(join_btn)

        async def on_clear(interaction: discord.Interaction) -> None:
            self.bw_race = None
            self.sc2_race = None
            self.map_vetoes = []
            await self.persist_and_refresh(interaction)

        clear_btn: discord.ui.Button[QueueSetupView] = discord.ui.Button(
            label="Clear All Selections",
            emoji="🗑️",
            style=discord.ButtonStyle.danger,
            row=0,
        )
        clear_btn.callback = on_clear  # type: ignore[method-assign]
        self.add_item(clear_btn)

        async def on_cancel(interaction: discord.Interaction) -> None:
            if interaction.message is not None:
                await interaction.message.delete()

        cancel_btn: discord.ui.Button[QueueSetupView] = discord.ui.Button(
            label="Cancel",
            emoji="✖️",
            style=discord.ButtonStyle.danger,
            row=0,
        )
        cancel_btn.callback = on_cancel  # type: ignore[method-assign]
        self.add_item(cancel_btn)

        # Row 1-3: selects
        self.add_item(BwRaceSelect(self.bw_race))
        self.add_item(Sc2RaceSelect(self.sc2_race))
        self.add_item(MapVetoSelect(self.map_vetoes))

    async def persist_and_refresh(self, interaction: discord.Interaction) -> None:
        """Save preferences to backend and refresh the embed."""
        # Fire-and-forget preferences save
        try:
            races: list[str] = []
            if self.bw_race:
                races.append(self.bw_race)
            if self.sc2_race:
                races.append(self.sc2_race)
            async with get_session().put(
                f"{BACKEND_URL}/preferences_1v1",
                json={
                    "discord_uid": self.discord_user_id,
                    "last_chosen_races": races,
                    "last_chosen_vetoes": sorted(self.map_vetoes),
                },
            ) as resp:
                await resp.json()
        except Exception:
            logger.warning("Failed to persist preferences", exc_info=True)

        new_view = QueueSetupView(
            self.discord_user_id, self.bw_race, self.sc2_race, self.map_vetoes
        )
        embed = build_queue_setup_embed(self.bw_race, self.sc2_race, self.map_vetoes)
        await interaction.response.edit_message(embed=embed, view=new_view)


class _CancelQueueButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Cancel Queue",
            emoji="✖️",
            style=discord.ButtonStyle.danger,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await _leave_queue(interaction)


class QueueSearchingView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(_CancelQueueButton())


class MatchFoundView(discord.ui.View):
    def __init__(self, match_id: int, match_data: dict) -> None:
        super().__init__(timeout=60)
        self.match_id = match_id
        self.match_data = match_data

        async def on_confirm(interaction: discord.Interaction) -> None:
            await _confirm_match(interaction, match_id)

        confirm_btn: discord.ui.Button[MatchFoundView] = discord.ui.Button(
            label="Confirm Match",
            emoji="✅",
            style=discord.ButtonStyle.green,
            row=0,
        )
        confirm_btn.callback = on_confirm  # type: ignore[method-assign]
        self.add_item(confirm_btn)

        async def on_abort(interaction: discord.Interaction) -> None:
            await _abort_match(interaction, match_id)

        abort_btn: discord.ui.Button[MatchFoundView] = discord.ui.Button(
            label="Abort Match",
            emoji="🛑",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        abort_btn.callback = on_abort  # type: ignore[method-assign]
        self.add_item(abort_btn)


class MatchReportView(discord.ui.View):
    def __init__(
        self,
        match_id: int,
        p1_name: str,
        p2_name: str,
        match_data: dict | None = None,
        p1_info: dict[str, Any] | None = None,
        p2_info: dict[str, Any] | None = None,
        *,
        report_locked: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.match_id = match_id
        self._match_data = match_data or {}
        self._p1_info = p1_info
        self._p2_info = p2_info
        self.report_select = MatchReportSelect(match_id, p1_name, p2_name)
        self.report_select.disabled = report_locked
        self.add_item(self.report_select)

    async def submit_report(
        self, interaction: discord.Interaction, report: str
    ) -> None:
        await interaction.response.defer()
        try:
            async with get_session().put(
                f"{BACKEND_URL}/matches_1v1/{self.match_id}/report",
                json={
                    "discord_uid": interaction.user.id,
                    "report": report,
                },
            ) as resp:
                data = await resp.json()

            if not data.get("success"):
                await interaction.followup.send(
                    embed=QueueErrorEmbed(
                        data.get("message") or "Failed to submit report."
                    ),
                    ephemeral=True,
                )
                return

            # Update embed in-place: show the submitted report and lock the dropdown.
            # The WS listener will send the final result as a separate message.
            for option in self.report_select.options:
                option.default = option.value == report
            self.report_select.disabled = True
            new_embed = MatchInfoEmbed(
                self._match_data, self._p1_info, self._p2_info, pending_report=report
            )
            await interaction.edit_original_response(embed=new_embed, view=self)

        except Exception:
            logger.exception("Failed to submit match report")
            await interaction.followup.send(
                embed=QueueErrorEmbed("An unexpected error occurred."),
                ephemeral=True,
            )


# ---------------------------------------------------------------------------
# HTTP action helpers
# ---------------------------------------------------------------------------


async def _fetch_mmrs(discord_uid: int) -> dict[str, int]:
    """Fetch all MMR rows for a player and return a {race: mmr} mapping."""
    try:
        async with get_session().get(f"{BACKEND_URL}/mmrs_1v1/{discord_uid}") as resp:
            data = await resp.json()
            return {row["race"]: row["mmr"] for row in data.get("mmrs", [])}
    except Exception:
        logger.warning("Failed to fetch MMRs", discord_uid=discord_uid)
        return {}


async def _join_queue(
    interaction: discord.Interaction,
    discord_user_id: int,
    bw_race: str | None,
    sc2_race: str | None,
    map_vetoes: list[str],
) -> None:
    if bw_race is None and sc2_race is None:
        await interaction.response.send_message(
            embed=QueueErrorEmbed("You must select at least one race."),
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    try:
        mmrs = await _fetch_mmrs(discord_user_id)

        async with get_session().post(
            f"{BACKEND_URL}/queue_1v1/join",
            json={
                "discord_uid": discord_user_id,
                "discord_username": interaction.user.name,
                "bw_race": bw_race,
                "sc2_race": sc2_race,
                "bw_mmr": mmrs.get(bw_race) if bw_race else None,
                "sc2_mmr": mmrs.get(sc2_race) if sc2_race else None,
                "map_vetoes": map_vetoes,
            },
        ) as resp:
            data = await resp.json()

        if not data.get("success"):
            await interaction.edit_original_response(
                embed=QueueErrorEmbed(data.get("message") or "Failed to join queue."),
                view=None,
            )
            return

        # Fetch queue stats for the searching embed
        stats: dict | None = None
        try:
            async with get_session().get(f"{BACKEND_URL}/queue_1v1/stats") as resp2:
                stats = await resp2.json()
        except Exception:
            pass

        await interaction.edit_original_response(
            embed=QueueSearchingEmbed(stats),
            view=QueueSearchingView(),
        )

        # Store a reference to this message so the WS listener can edit it
        # when a match is found (stops the timer and removes the cancel button).
        try:
            msg = await interaction.original_response()
            from bot.core.dependencies import get_cache

            get_cache().active_searching_messages[discord_user_id] = msg
        except Exception:
            logger.warning(
                "Could not cache searching message reference",
                discord_user_id=discord_user_id,
            )

    except Exception:
        logger.exception("Failed to join queue")
        await interaction.edit_original_response(
            embed=QueueErrorEmbed("An unexpected error occurred."),
            view=None,
        )


async def _leave_queue(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    try:
        async with get_session().delete(
            f"{BACKEND_URL}/queue_1v1/leave",
            json={"discord_uid": interaction.user.id},
        ) as resp:
            data = await resp.json()

        if not data.get("success"):
            await interaction.followup.send(
                embed=QueueErrorEmbed(data.get("message") or "Failed to leave queue."),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Queue Left",
            description="You have left the queue.",
            color=discord.Color.light_grey(),
        )
        await interaction.edit_original_response(embed=embed, view=None)

        # Clear the cached searching message reference.
        try:
            from bot.core.dependencies import get_cache

            get_cache().active_searching_messages.pop(interaction.user.id, None)
        except Exception:
            pass

    except Exception:
        logger.exception("Failed to leave queue")
        await interaction.followup.send(
            embed=QueueErrorEmbed("An unexpected error occurred."),
            ephemeral=True,
        )


async def _confirm_match(interaction: discord.Interaction, match_id: int) -> None:
    await interaction.response.defer()
    try:
        async with get_session().put(
            f"{BACKEND_URL}/matches_1v1/{match_id}/confirm",
            json={"discord_uid": interaction.user.id},
        ) as resp:
            data = await resp.json()

        if not data.get("success"):
            await interaction.followup.send(
                embed=QueueErrorEmbed("Failed to confirm match."),
                ephemeral=True,
            )
            return

        # Always show "waiting for opponent" — the WS listener sends a NEW
        # message with match details once both players have confirmed.
        embed = discord.Embed(
            title=f"✅ Match #{match_id} — Confirmed!",
            description="Waiting for your opponent to confirm...",
            color=discord.Color.gold(),
        )
        await interaction.edit_original_response(embed=embed, view=None)

    except Exception:
        logger.exception("Failed to confirm match")
        await interaction.followup.send(
            embed=QueueErrorEmbed("An unexpected error occurred."),
            ephemeral=True,
        )


async def _abort_match(interaction: discord.Interaction, match_id: int) -> None:
    await interaction.response.defer()
    try:
        async with get_session().put(
            f"{BACKEND_URL}/matches_1v1/{match_id}/abort",
            json={"discord_uid": interaction.user.id},
        ) as resp:
            data = await resp.json()

        if not data.get("success"):
            await interaction.followup.send(
                embed=QueueErrorEmbed(data.get("message") or "Failed to abort match."),
                ephemeral=True,
            )
            return

        await interaction.edit_original_response(
            embed=discord.Embed(
                title="🛑 Match Aborted",
                description="You have aborted the match. You will receive a summary shortly.",
                color=discord.Color.red(),
            ),
            view=None,
        )

    except Exception:
        logger.exception("Failed to abort match")
        await interaction.followup.send(
            embed=QueueErrorEmbed("An unexpected error occurred."),
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------


def register_queue_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="queue", description="Join the 1v1 ranked matchmaking queue")
    @app_commands.check(check_if_dm)
    async def queue_command(interaction: discord.Interaction) -> None:
        logger.debug(f"queue_command invoked by user={interaction.user.id}")
        await interaction.response.defer()

        # Load saved preferences
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

        embed = build_queue_setup_embed(bw_race, sc2_race, map_vetoes)
        view = QueueSetupView(
            discord_user_id=interaction.user.id,
            bw_race=bw_race,
            sc2_race=sc2_race,
            map_vetoes=map_vetoes,
        )
        await interaction.followup.send(embed=embed, view=view)
