"""
All Discord embed classes used across bot commands and event handlers.

Organized by domain.  Private helper functions used only by embed constructors
live next to the embeds that depend on them.
"""

import json
import time
from datetime import datetime
from typing import Any

import discord

from bot.core.config import (
    ALLOW_AI_PLAYERS,
    CURRENT_SEASON,
    ENABLE_REPLAY_VALIDATION,
    EXPECTED_LOBBY_SETTINGS,
    MAX_MAP_VETOES,
    MAX_MATCH_SLOTS,
    MAX_QUEUE_SLOTS,
    QUICKSTART_URL,
    TOS_MIRROR_URL,
    TOS_URL,
)
from bot.helpers.emotes import (
    get_flag_emote,
    get_game_emote,
    get_globe_emote,
    get_race_emote,
    get_rank_emote,
)
from bot.helpers.i18n import LOCALE_DISPLAY_NAMES
from common.datetime_helpers import (
    ensure_utc,
    to_discord_timestamp,
    to_display,
    utc_now,
)
from common.json_types import Country, GeographicRegion
from common.lookups.country_lookups import get_country_by_code
from common.lookups.map_lookups import get_map_by_short_name, get_maps
from common.lookups.mod_lookups import get_mod_by_code
from common.lookups.race_lookups import get_race_by_code, get_races
from common.lookups.region_lookups import (
    get_game_region_by_code,
    get_game_server_by_code,
    get_geographic_region_by_code,
)


# =========================================================================
# Generic
# =========================================================================


class ErrorEmbed(discord.Embed):
    """Standard red error embed used across all commands."""

    def __init__(self, title: str, description: str) -> None:
        super().__init__(
            title=title,
            description=description,
            color=discord.Color.red(),
        )


class UnsupportedGameModeEmbed(discord.Embed):
    def __init__(self, game_mode: str) -> None:
        super().__init__(
            title="🚧 Unsupported Game Mode",
            description=f"`{game_mode}` is not yet supported. Only `1v1` is currently available.",
            color=discord.Color.orange(),
        )


# =========================================================================
# Queue / Match lifecycle  (queue_command + ws_listener + replay_handler)
# =========================================================================

_NUMBER_EMOTES = [":one:", ":two:", ":three:", ":four:"]


def _race_display(race_code: str) -> str:
    races = get_races()
    race = races.get(race_code)
    return race["name"] if race else race_code


def _get_map_game(map_name: str) -> str:
    """Return 'bw' or 'sc2' for a map by looking it up in the map pool."""
    maps = get_maps(game_mode="1v1", season=CURRENT_SEASON) or {}
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
    """Format server code to 'Server Name (Region Name)'."""
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


class QueueSetupEmbed(discord.Embed):
    """Queue setup configuration display."""

    def __init__(
        self,
        bw_race: str | None,
        sc2_race: str | None,
        map_vetoes: list[str],
    ) -> None:
        super().__init__(
            title="🎮 Matchmaking Queue",
            color=discord.Color.blue(),
        )

        self.add_field(
            name="⚠️ NEW PLAYERS START HERE ⚠️",
            value=f"📘 **QUICK START GUIDE:**  [READ THIS BEFORE YOUR FIRST MATCH!]({QUICKSTART_URL})\n",
            inline=False,
        )

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
        self.add_field(name="Selected Races", value=race_value, inline=False)

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
        self.add_field(
            name=f"Vetoed Maps ({veto_count}/{MAX_MAP_VETOES})",
            value=veto_value,
            inline=False,
        )


class MatchConfirmedEmbed(discord.Embed):
    def __init__(self, match_id: int) -> None:
        super().__init__(
            title=f"✅ Match #{match_id} — Confirmed!",
            description="Waiting for your opponent to confirm...",
            color=discord.Color.gold(),
        )


class MatchAbortAckEmbed(discord.Embed):
    def __init__(self) -> None:
        super().__init__(
            title="🛑 Match Aborted",
            description="You have aborted the match. You will receive a summary shortly.",
            color=discord.Color.red(),
        )


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

        p1_country = (p1_info.get("nationality") or "XX") if p1_info else "XX"
        p2_country = (p2_info.get("nationality") or "XX") if p2_info else "XX"
        p1_flag = get_flag_emote(p1_country)
        p2_flag = get_flag_emote(p2_country)

        p1_rank_emote = get_rank_emote("U")
        p2_rank_emote = get_rank_emote("U")

        p1_race_emote = get_race_emote(p1_race) if p1_race else ""
        p2_race_emote = get_race_emote(p2_race) if p2_race else ""

        title = (
            f"Match #{match_id}:\n"
            f"{p1_rank_emote} {p1_flag} {p1_race_emote} {p1_name} ({p1_mmr}) "
            f"vs "
            f"{p2_rank_emote} {p2_flag} {p2_race_emote} {p2_name} ({p2_mmr})"
        )

        super().__init__(title=title, description="", color=discord.Color.teal())

        self.add_field(name="", value="", inline=False)

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

        self.add_field(name="", value="", inline=False)

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

        self.add_field(name="", value="", inline=False)

        self.add_field(
            name="🔧 Match Settings:",
            value=(
                f"- Server: `{server_full}`\n"
                f"- In-Game Channel: `SCEvoLadder`\n"
                f"- Locked Alliances: `{EXPECTED_LOBBY_SETTINGS['locked_alliances']}`"
            ),
            inline=True,
        )

        self.add_field(
            name="\u3164",
            value=(
                f"- Game Privacy: `{EXPECTED_LOBBY_SETTINGS['privacy']}`\n"
                f"- Game Speed: `{EXPECTED_LOBBY_SETTINGS['speed']}`\n"
                f"- Game Duration: `{EXPECTED_LOBBY_SETTINGS['duration']}`"
            ),
            inline=True,
        )

        self.add_field(name="", value="", inline=False)
        self.add_field(name="", value="", inline=False)

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

        if ENABLE_REPLAY_VALIDATION and not replay_uploaded:
            footer_text = (
                "ℹ️ To report the match result, upload a replay. "
                "The dropdown menus below will unlock once a valid replay is uploaded."
            )
        else:
            footer_text = "ℹ️ Report the match result using the dropdown menus below."
        self.set_footer(text=footer_text)


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


# =========================================================================
# Setup
# =========================================================================

_COUNTRY_LIMIT_NOTE = (
    "**Due to Discord UI limitations, only 49 common nationalities are listed here.**\n"
    "- If your nationality is not listed, select **Other** (page 2), then use `/setcountry` "
    "to set your exact nationality.\n"
    "- If you are non-representing, select **Other** (page 2), then use `/setcountry` "
    "to select **Non-representing**."
)


class SetupIntroEmbed(discord.Embed):
    def __init__(self) -> None:
        super().__init__(
            title="⚙️ Player Setup",
            description=(
                "Welcome to EvoLadder! Click **Begin Setup** to configure your player profile.\n\n"
                "You will need to provide:\n"
                "- A **User ID** (your display name on the ladder)\n"
                "- Your **BattleTag** (e.g. `Username#1234`)\n"
                "- Your **nationality**, **location**, and **language**\n"
                "- Optional **alternative IDs**"
            ),
            color=discord.Color.blue(),
        )


class SetupValidationErrorEmbed(discord.Embed):
    def __init__(self, title: str, error: str) -> None:
        super().__init__(
            title=f"❌ {title}",
            description=f"**Error:** {error}\n\nPlease try again.",
            color=discord.Color.red(),
        )


class SetupSelectionEmbed(discord.Embed):
    def __init__(
        self,
        country: Country | None = None,
        region: GeographicRegion | None = None,
        language: str | None = None,
    ) -> None:
        super().__init__(
            title="⚙️ Setup — Nationality, Location & Language",
            color=discord.Color.blue(),
        )
        selected_lines: list[str] = []
        if country:
            selected_lines.append(
                f"- Nationality: {get_flag_emote(country['code'])} {country['name']}"
            )
        if region:
            selected_lines.append(
                f"- Location: {get_globe_emote(region['globe_emote_code'])} {region['name']}"
            )
        if language:
            entry = LOCALE_DISPLAY_NAMES.get(language)
            flag, display = (entry[1], entry[0]) if entry else ("", language)
            selected_lines.append(f"- Language: {flag} {display}")

        if selected_lines:
            selected_block = "**Selected:**\n" + "\n".join(selected_lines) + "\n\n"
        else:
            selected_block = ""

        if country and region and language:
            self.description = selected_block + "Click **Confirm** to proceed."
        else:
            missing: list[str] = []
            if not country:
                missing.append("nationality")
            if not region:
                missing.append("location")
            if not language:
                missing.append("language")
            self.description = (
                selected_block
                + f"Please select your {', '.join(missing)}.\n\n{_COUNTRY_LIMIT_NOTE}"
            )


class SetupPreviewEmbed(discord.Embed):
    def __init__(
        self,
        player_name: str,
        battletag: str,
        alt_ids: list[str],
        country: Country,
        region: GeographicRegion,
        language: str,
    ) -> None:
        super().__init__(
            title="🔍 Preview Setup Information",
            description="Please review your setup information before confirming:",
            color=discord.Color.blue(),
        )
        self.add_field(name=":id: **User ID**", value=f"`{player_name}`", inline=False)
        self.add_field(
            name=":hash: **BattleTag**", value=f"`{battletag}`", inline=False
        )
        self.add_field(
            name=f"{get_flag_emote(country['code'])} **Nationality**",
            value=f"`{country['name']} ({country['code']})`",
            inline=False,
        )
        self.add_field(
            name=f"{get_globe_emote(region['globe_emote_code'])} **Location**",
            value=f"`{region['name']}`",
            inline=False,
        )
        self.add_field(
            name="🌐 **Language**",
            value=f"`{LOCALE_DISPLAY_NAMES[language][0] if language in LOCALE_DISPLAY_NAMES else language}`",
            inline=False,
        )
        alt_display = ", ".join(f"`{a}`" for a in alt_ids) if alt_ids else "`None`"
        self.add_field(name=":id: **Alternative IDs**", value=alt_display, inline=False)


class SetupSuccessEmbed(discord.Embed):
    def __init__(
        self,
        player_name: str,
        battletag: str,
        alt_ids: list[str],
        country: Country,
        region: GeographicRegion,
        language: str,
    ) -> None:
        super().__init__(
            title="✅ Setup Complete!",
            description="Your player profile has been successfully configured.",
            color=discord.Color.green(),
        )
        self.add_field(name=":id: **User ID**", value=f"`{player_name}`", inline=False)
        self.add_field(
            name=":hash: **BattleTag**", value=f"`{battletag}`", inline=False
        )
        self.add_field(
            name=f"{get_flag_emote(country['code'])} **Nationality**",
            value=f"`{country['name']} ({country['code']})`",
            inline=False,
        )
        self.add_field(
            name=f"{get_globe_emote(region['globe_emote_code'])} **Location**",
            value=f"`{region['name']}`",
            inline=False,
        )
        self.add_field(
            name="🌐 **Language**",
            value=f"`{LOCALE_DISPLAY_NAMES[language][0] if language in LOCALE_DISPLAY_NAMES else language}`",
            inline=False,
        )
        alt_display = ", ".join(f"`{a}`" for a in alt_ids) if alt_ids else "`None`"
        self.add_field(name=":id: **Alternative IDs**", value=alt_display, inline=False)


# =========================================================================
# Profile
# =========================================================================


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


# =========================================================================
# Terms of Service
# =========================================================================


class TermsOfServiceEmbed(discord.Embed):
    def __init__(self) -> None:
        super().__init__(
            title="📜 Terms of Service",
            description=(
                "Please read our Terms of Service, User Conduct guidelines, Privacy Policy, and Refund Policy. **You must accept these terms in order to use the SC: Evo Complete Ladder Bot.**\n\n"
                "**Official Terms of Service:**\n"
                f"🔗 [SC: Evo Ladder ToS]({TOS_URL})\n"
                f"🔗 [EvoLadderBot ToS (Mirror)]({TOS_MIRROR_URL})\n\n"
                "By clicking **✅ I Accept These Terms** below, you confirm that you have read and agree to abide by the Terms of Service. "
                "You can withdraw your agreement to these terms at any time by using this command again and clicking **❌ I Decline These Terms** below.\n\n"
                "**⚠️ Failure to read or understand these terms is NOT AN ACCEPTABLE DEFENSE for violating them, and may result in your removal from the Service.**"
            ),
            color=discord.Color.blue(),
        )


class TermsOfServiceAcceptedEmbed(discord.Embed):
    def __init__(self) -> None:
        super().__init__(
            title="✅ Terms of Service Accepted",
            description=(
                "Thank you for agreeing to the Terms of Service. "
                "Welcome to the SC: Evo Complete Ladder Bot!"
            ),
            color=discord.Color.green(),
        )


class TermsOfServiceDeclinedEmbed(discord.Embed):
    def __init__(self) -> None:
        super().__init__(
            title="❌ Terms of Service Declined",
            description=(
                "You have declined the Terms of Service. "
                "As such, you may not use the SC: Evo Complete Ladder Bot."
            ),
            color=discord.Color.red(),
        )


# =========================================================================
# Set Country
# =========================================================================


class SetCountryNotFoundEmbed(discord.Embed):
    def __init__(self, country: str, locale: str = "enUS"):
        from common.i18n import t

        super().__init__(
            title="❌ Country Not Found",
            description=t(
                "bot.commands.user.setcountry.not_found.description",
                locale,
                country=country,
            ),
            color=discord.Color.red(),
        )


class SetCountryPreviewEmbed(discord.Embed):
    def __init__(self, country: Country, locale: str = "enUS"):
        from common.i18n import t

        super().__init__(
            title=t("bot.commands.user.setcountry.preview.title", locale),
            description=t("bot.commands.user.setcountry.preview.description", locale),
            color=discord.Color.blue(),
        )
        self.add_field(
            name=f"{get_flag_emote(country['code'])} **Nationality**",
            value=f"`{country['name']} ({country['code']})`",
        )


class SetCountryConfirmEmbed(discord.Embed):
    def __init__(self, country: Country, locale: str = "enUS"):
        from common.i18n import t

        super().__init__(
            title=t("bot.commands.user.setcountry.confirm.title", locale),
            description=t("bot.commands.user.setcountry.confirm.description", locale),
            color=discord.Color.blue(),
        )
        self.add_field(
            name=f"{get_flag_emote(country['code'])} **Nationality**",
            value=f"`{country['name']} ({country['code']})`",
        )


# =========================================================================
# Admin: Ban
# =========================================================================


class BanPreviewEmbed(discord.Embed):
    def __init__(self, target: discord.User) -> None:
        super().__init__(
            title="⚠️ Toggle Ban",
            description=(
                f"You are about to toggle the ban status for:\n\n"
                f"**User:** {target.mention} (`{target.name}` / `{target.id}`)\n\n"
                "If the user is currently **unbanned**, they will be **banned**.\n"
                "If the user is currently **banned**, they will be **unbanned**.\n\n"
                "Please confirm below."
            ),
            color=discord.Color.orange(),
        )


class BanSuccessEmbed(discord.Embed):
    def __init__(self, target: discord.User, new_is_banned: bool) -> None:
        action = "banned" if new_is_banned else "unbanned"
        emoji = "🔨" if new_is_banned else "✅"
        color = discord.Color.red() if new_is_banned else discord.Color.green()
        super().__init__(
            title=f"{emoji} User {action.title()}",
            description=(
                f"**User:** {target.mention} (`{target.name}` / `{target.id}`)\n"
                f"**Status:** {action.upper()}"
            ),
            color=color,
        )


# =========================================================================
# Admin: Snapshot
# =========================================================================


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
    dt = ensure_utc(iso_str)
    if dt is None:
        return "   ?s"
    elapsed = int((utc_now() - dt).total_seconds())
    return f"{elapsed:>4d}s"


def _format_queue_player(entry: dict) -> str:
    """Format a single queue player as a monospace backtick string."""
    player_name = (entry.get("player_name") or "Unknown")[:12]
    name_padded = f"{player_name:<12}"

    bw_race_code = entry.get("bw_race")
    sc2_race_code = entry.get("sc2_race")

    bw_part = f"  {_race_short(bw_race_code)}" if bw_race_code else "    "
    sc2_part = f"  {_race_short(sc2_race_code)}" if sc2_race_code else "    "

    cc = "  "

    player_str = f"{bw_part} {sc2_part} {cc} {name_padded}"
    wait_time = _elapsed_seconds(entry.get("joined_at"))

    return f"`{player_str}` `{wait_time}`"


def _format_blank_queue_slot() -> str:
    return f"`{' ' * 25}` `{' ' * 5}`"


def _format_match_slot(match: dict, id_width: int) -> str:
    """Format a single active match as a monospace backtick string."""
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
    blank_player = " " * 15
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


class QueueSnapshotEmbed(discord.Embed):
    """Embed 2: Queue players in monospace backtick format, two columns of 15."""

    def __init__(self, queue: list[dict]) -> None:
        queue_size = len(queue)
        super().__init__(
            title="🎮 Queue Status",
            color=discord.Color.green(),
        )

        description = f"**Players in Queue:** {queue_size}\n"

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


# =========================================================================
# Admin: Match Details
# =========================================================================

_REPORT_LABELS: dict[str | None, str] = {
    "player_1_win": "Player 1 Won",
    "player_2_win": "Player 2 Won",
    "draw": "Draw",
    "invalidated": "Invalidated",
    None: "Not Reported",
}


def _player_prefix(
    race: str, nationality: str | None, letter_rank: str | None = None
) -> str:
    """Build flag/race prefix for a player, optionally with rank emote."""
    parts: list[str] = []
    if letter_rank:
        try:
            parts.append(get_rank_emote(letter_rank))
        except ValueError:
            pass
    if nationality:
        parts.append(str(get_flag_emote(nationality)))
    try:
        parts.append(get_race_emote(race))
    except ValueError:
        parts.append("🎮")
    return " ".join(parts)


def _result_display(result: str | None, p1_name: str, p2_name: str) -> str:
    if result == "player_1_win":
        return f"🏆 **{p1_name}** won"
    if result == "player_2_win":
        return f"🏆 **{p2_name}** won"
    if result == "draw":
        return "⚖️ **Draw**"
    if result == "invalidated":
        return "❌ **Invalidated**"
    return "⏳ **In Progress**"


def _format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


def _admin_server_display(server_code: str | None) -> str:
    """Resolve server code to full name, falling back to the code itself."""
    if not server_code:
        return "Unknown"
    server = get_game_server_by_code(server_code)
    if server:
        return f"{server['name']} ({server_code})"
    return server_code


class MatchNotFoundEmbed(discord.Embed):
    def __init__(self, match_id: int) -> None:
        super().__init__(
            title="❌ Match Not Found",
            description=f"No match found with ID `{match_id}`.",
            color=discord.Color.red(),
        )


class AdminMatchEmbed(discord.Embed):
    """Main admin match overview — full matches_1v1 row data."""

    def __init__(
        self,
        match: dict[str, Any],
        player_1: dict[str, Any] | None,
        player_2: dict[str, Any] | None,
        admin: dict[str, Any] | None,
    ) -> None:
        match_id = match.get("id", "?")
        result = match.get("match_result")

        if result is None:
            color = discord.Color.blue()
        elif result == "invalidated":
            color = discord.Color.dark_grey()
        else:
            color = discord.Color.green()

        p1_name = match.get("player_1_name") or "Unknown"
        p2_name = match.get("player_2_name") or "Unknown"
        p1_race = match.get("player_1_race") or ""
        p2_race = match.get("player_2_race") or ""
        p1_mmr = match.get("player_1_mmr") or 0
        p2_mmr = match.get("player_2_mmr") or 0
        p1_uid = match.get("player_1_discord_uid") or 0
        p2_uid = match.get("player_2_discord_uid") or 0

        p1_nat = player_1.get("nationality") if player_1 else None
        p2_nat = player_2.get("nationality") if player_2 else None

        p1_prefix = _player_prefix(p1_race, p1_nat)
        p2_prefix = _player_prefix(p2_race, p2_nat)

        super().__init__(
            title=f"🔍 Admin Match #{match_id} State",
            description=(
                f"{p1_prefix} **{p1_name}** (MMR: {p1_mmr})"
                f"  vs  "
                f"{p2_prefix} **{p2_name}** (MMR: {p2_mmr})"
            ),
            color=color,
        )

        self.add_field(
            name="",
            value=(
                f"**Result:** {_result_display(result, p1_name, p2_name)}\n"
                f"**Player 1 UID:** `{p1_uid}`\n"
                f"**Player 2 UID:** `{p2_uid}`"
            ),
            inline=False,
        )

        p1_report = _REPORT_LABELS.get(
            match.get("player_1_report"), match.get("player_1_report") or "Not Reported"
        )
        p2_report = _REPORT_LABELS.get(
            match.get("player_2_report"), match.get("player_2_report") or "Not Reported"
        )
        reports_text = f"**{p1_name}:** {p1_report}\n**{p2_name}:** {p2_report}"

        admin_intervened = match.get("admin_intervened", False)
        if admin_intervened:
            admin_uid = match.get("admin_discord_uid")
            admin_username = admin.get("discord_username") if admin else None
            if admin_username:
                resolved_text = f"✅ Yes\n{admin_username} (`{admin_uid}`)"
            else:
                resolved_text = f"✅ Yes\n`{admin_uid}`"
        else:
            resolved_text = "❌ No"

        self.add_field(
            name="📊 Original Player Reports", value=reports_text, inline=True
        )
        self.add_field(name="🛡️ Admin Resolved", value=resolved_text, inline=True)

        p1_change = match.get("player_1_mmr_change")
        p2_change = match.get("player_2_mmr_change")
        if p1_change is not None or p2_change is not None:
            p1_c = p1_change or 0
            p2_c = p2_change or 0
            p1_new = p1_mmr + p1_c
            p2_new = p2_mmr + p2_c
            mmr_text = (
                f"**{p1_name}:** `{p1_c:+d}` ({p1_mmr} → {p1_new})\n"
                f"**{p2_name}:** `{p2_c:+d}` ({p2_mmr} → {p2_new})"
            )
            self.add_field(name="📈 MMR Changes", value=mmr_text, inline=False)

        map_name = match.get("map_name") or "Unknown"
        server_code = match.get("server_name")
        info_text = (
            f"**Map:** `{map_name}`\n**Server:** `{_admin_server_display(server_code)}`"
        )
        info_text += (
            f"\n**Assigned:** {to_discord_timestamp(raw=match.get('assigned_at'))}"
        )
        if match.get("completed_at"):
            info_text += f"\n**Completed:** {to_discord_timestamp(raw=match.get('completed_at'))}"
        self.add_field(name="🗺️ Match Info", value=info_text, inline=False)

        raw: dict[str, Any] = {}
        for key in (
            "id",
            "player_1_discord_uid",
            "player_2_discord_uid",
            "player_1_name",
            "player_2_name",
            "player_1_race",
            "player_2_race",
            "player_1_mmr",
            "player_2_mmr",
            "player_1_report",
            "player_2_report",
            "match_result",
            "player_1_mmr_change",
            "player_2_mmr_change",
            "map_name",
            "server_name",
            "assigned_at",
            "completed_at",
            "admin_intervened",
            "admin_discord_uid",
            "player_1_replay_path",
            "player_1_replay_row_id",
            "player_1_uploaded_at",
            "player_2_replay_path",
            "player_2_replay_row_id",
            "player_2_uploaded_at",
        ):
            val = match.get(key)
            if isinstance(val, datetime):
                raw[key] = str(val)
            elif key.endswith("_replay_path") and isinstance(val, str):
                raw[key] = val.rsplit("/", 1)[-1] if "/" in val else val
            else:
                raw[key] = val

        raw_json = json.dumps(raw, indent=2, ensure_ascii=False)
        if len(raw_json) > 950:
            raw_json = raw_json[:950] + "\n..."
        self.add_field(
            name="📋 Raw Match Data",
            value=f"```json\n{raw_json}\n```",
            inline=False,
        )

        p1_replay = match.get("player_1_replay_path")
        p2_replay = match.get("player_2_replay_path")
        p1_status = "✅ Uploaded" if p1_replay else "❌ No"
        p2_status = "✅ Uploaded" if p2_replay else "❌ No"
        replay_text = f"**{p1_name}:** {p1_status}\n**{p2_name}:** {p2_status}"
        self.add_field(name="🎬 Replay Status", value=replay_text, inline=False)


class AdminReplayDetailsEmbed(discord.Embed):
    """Per-player replay details — mirrors the player-facing ReplaySuccessEmbed
    format with full verification."""

    def __init__(
        self,
        player_num: int,
        replay: dict[str, Any],
        verification: dict[str, Any] | None,
        replay_url: str | None,
    ) -> None:
        super().__init__(
            title=f"Player #{player_num} Replay Details",
            description="Summary of the uploaded replay for the match.",
            color=discord.Color.light_grey(),
        )

        p1_name = replay.get("player_1_name") or "Player 1"
        p2_name = replay.get("player_2_name") or "Player 2"
        p1_race = replay.get("player_1_race") or ""
        p2_race = replay.get("player_2_race") or ""
        result_str = replay.get("match_result") or "?"
        map_name = replay.get("map_name") or "Unknown"
        duration = replay.get("game_duration_seconds") or 0
        observers: list[str] = replay.get("observers") or []

        try:
            p1_emote = get_race_emote(p1_race)
        except ValueError:
            p1_emote = "🎮"
        try:
            p2_emote = get_race_emote(p2_race)
        except ValueError:
            p2_emote = "🎮"

        if result_str in ("player_1_win", "1"):
            result_display = f"🏆 {p1_name}"
        elif result_str in ("player_2_win", "2"):
            result_display = f"🏆 {p2_name}"
        elif result_str in ("draw", "0"):
            result_display = "⚖️ Draw"
        else:
            result_display = str(result_str)

        map_display = map_name.replace(" (", "\n(", 1) if "(" in map_name else map_name

        self.add_field(name="", value="\u3164", inline=False)

        self.add_field(
            name="⚔️ Matchup",
            value=f"**{p1_emote} {p1_name}** vs\n**{p2_emote} {p2_name}**",
            inline=True,
        )
        self.add_field(name="🏆 Result", value=result_display, inline=True)
        self.add_field(name="🗺️ Map", value=map_display, inline=True)

        start_time = to_display(raw=replay.get("replay_time"))
        self.add_field(name="🕒 Game Start Time", value=start_time, inline=True)
        self.add_field(
            name="🕒 Game Duration",
            value=_format_duration(duration),
            inline=True,
        )

        obs_text = (
            f"⚠️ {', '.join(observers)}" if observers else "✅ No observers present"
        )
        self.add_field(name="🔍 Observers", value=obs_text, inline=True)

        self.add_field(name="", value="\u3164", inline=False)

        if verification:
            self.add_field(
                name="☑️ Replay Verification",
                value=format_verification(verification, enforcement_enabled=False),
                inline=False,
            )

        if replay_url:
            self.add_field(
                name="📥 Download",
                value=f"[Replay File]({replay_url})",
                inline=False,
            )


# =========================================================================
# Admin: Resolve
# =========================================================================


def _get_result_display(result: str, data: dict) -> str:
    """Build the result display string matching the alpha format."""
    p1_name = data.get("player_1_name", "?")
    p2_name = data.get("player_2_name", "?")
    p1_race = data.get("player_1_race", "")
    p2_race = data.get("player_2_race", "")

    try:
        p1_emote = get_race_emote(p1_race)
    except ValueError:
        p1_emote = "🎮"
    try:
        p2_emote = get_race_emote(p2_race)
    except ValueError:
        p2_emote = "🎮"

    if result == "player_1_win":
        return f"🏆 **{p1_emote} {p1_name}**"
    elif result == "player_2_win":
        return f"🏆 **{p2_emote} {p2_name}**"
    elif result == "draw":
        return "⚖️ **Draw**"
    elif result == "invalidated":
        return "❌ **Match Invalidated**"
    return result


class ResolvePreviewEmbed(discord.Embed):
    def __init__(
        self, match_id: int, result: str, result_display: str, reason: str | None
    ) -> None:
        description = (
            f"**Match ID:** {match_id}\n"
            f"**Resolution:** {result_display}\n"
            f"**Internal Code:** `{result}`"
        )
        if reason:
            description += f"\n**Reason:** {reason}"
        description += "\n\nThis will update the match result and MMR. Confirm?"
        super().__init__(
            title="⚠️ Admin: Confirm Match Resolution",
            description=description,
            color=discord.Color.orange(),
        )


class AdminResolutionEmbed(discord.Embed):
    """Admin Resolution embed — used for admin confirmation, player DMs,
    and match log channel."""

    def __init__(
        self,
        data: dict,
        *,
        reason: str | None,
        admin_name: str,
        is_admin_confirm: bool = False,
    ) -> None:
        match_id = data.get("match_id", "?")
        result = data.get("result", "?")
        p1_name = data.get("player_1_name", "?")
        p2_name = data.get("player_2_name", "?")
        p1_race = data.get("player_1_race", "")
        p2_race = data.get("player_2_race", "")
        p1_nationality = data.get("player_1_nationality")
        p2_nationality = data.get("player_2_nationality")
        p1_rank = data.get("player_1_letter_rank")
        p2_rank = data.get("player_2_letter_rank")
        p1_old = data.get("player_1_mmr", 0)
        p2_old = data.get("player_2_mmr", 0)
        p1_new = data.get("player_1_mmr_new", 0)
        p2_new = data.get("player_2_mmr_new", 0)
        p1_change = data.get("player_1_mmr_change", 0)
        p2_change = data.get("player_2_mmr_change", 0)

        p1_prefix = _player_prefix(p1_race, p1_nationality, p1_rank)
        p2_prefix = _player_prefix(p2_race, p2_nationality, p2_rank)

        title_icon = "✅" if is_admin_confirm else "⚖️"
        color = discord.Color.green() if is_admin_confirm else discord.Color.gold()

        super().__init__(
            title=f"{title_icon} Match #{match_id} Admin Resolution",
            description=(
                f"**{p1_prefix} {p1_name} ({p1_old} → {p1_new})** "
                f"vs "
                f"**{p2_prefix} {p2_name} ({p2_old} → {p2_new})**"
            ),
            color=color,
        )

        self.add_field(name="", value="\u3164", inline=False)

        result_display = _get_result_display(result, data)
        self.add_field(name="**Result:**", value=result_display, inline=True)

        mmr_text = (
            f"• {p1_name}: `{p1_change:+d} ({p1_old} → {p1_new})`\n"
            f"• {p2_name}: `{p2_change:+d} ({p2_old} → {p2_new})`"
        )
        self.add_field(name="**MMR Changes:**", value=mmr_text, inline=True)

        intervention_text = f"**Resolved by:** {admin_name}"
        if reason:
            intervention_text += f"\n**Reason:** {reason}"
        self.add_field(
            name="⚠️ **Admin Intervention:**",
            value=intervention_text,
            inline=False,
        )


# =========================================================================
# Admin: Status Reset
# =========================================================================


class StatusResetPreviewEmbed(discord.Embed):
    def __init__(self, target: discord.User) -> None:
        super().__init__(
            title="⚠️ Admin: Confirm Status Reset",
            description=(
                f"**Player:** {target.mention} (`{target.name}` / `{target.id}`)\n\n"
                "This will reset the player's state to **idle**, clearing their "
                "current match mode and match ID. Use this to fix stuck players.\n\n"
                "Confirm?"
            ),
            color=discord.Color.orange(),
        )


class StatusResetSuccessEmbed(discord.Embed):
    def __init__(
        self,
        target: discord.User,
        old_status: str | None,
        admin: discord.User | discord.Member,
    ) -> None:
        super().__init__(
            title="✅ Admin: Player Status Reset",
            description=(
                f"**Player:** {target.mention} (`{target.name}` / `{target.id}`)\n"
                f"**Previous State:** `{old_status or 'unknown'}`\n"
                f"**New State:** `idle`"
            ),
            color=discord.Color.green(),
        )
        self.add_field(name="👤 Admin", value=admin.name, inline=True)


# =========================================================================
# Owner: Admin
# =========================================================================


class ToggleAdminPreviewEmbed(discord.Embed):
    def __init__(self, target: discord.User) -> None:
        super().__init__(
            title="⚠️ Toggle Admin Role",
            description=(
                f"You are about to toggle the admin role for:\n\n"
                f"**User:** {target.mention} (`{target.name}` / `{target.id}`)\n\n"
                "- If the user is **not an admin**, they will be **promoted to admin**.\n"
                "- If the user is an **active admin**, they will be **demoted to inactive**.\n"
                "- If the user is **inactive**, they will be **re-promoted to admin**.\n"
                "- **Owners cannot be demoted** through this command.\n\n"
                "Please confirm below."
            ),
            color=discord.Color.orange(),
        )


class ToggleAdminSuccessEmbed(discord.Embed):
    def __init__(self, target: discord.User, action: str, new_role: str) -> None:
        if action == "promoted":
            emoji = "⬆️"
            color = discord.Color.green()
        elif action == "demoted":
            emoji = "⬇️"
            color = discord.Color.orange()
        else:
            emoji = "➕"
            color = discord.Color.green()

        super().__init__(
            title=f"{emoji} Admin Role Updated",
            description=(
                f"**User:** {target.mention} (`{target.name}` / `{target.id}`)\n"
                f"**Action:** {action.title()}\n"
                f"**New Role:** `{new_role}`"
            ),
            color=color,
        )


# =========================================================================
# Owner: MMR
# =========================================================================


class SetMMRPreviewEmbed(discord.Embed):
    def __init__(self, target: discord.User, race: str, new_mmr: int) -> None:
        try:
            race_emote = get_race_emote(race)
        except ValueError:
            race_emote = "🎮"

        super().__init__(
            title="⚠️ Set MMR",
            description=(
                f"You are about to set the MMR for:\n\n"
                f"**User:** {target.mention} (`{target.name}` / `{target.id}`)\n"
                f"**Race:** {race_emote} `{race}`\n"
                f"**New MMR:** `{new_mmr}`\n\n"
                "This is an **idempotent SET** — the MMR will be overwritten to this exact value.\n\n"
                "Please confirm below."
            ),
            color=discord.Color.orange(),
        )


class SetMMRSuccessEmbed(discord.Embed):
    def __init__(
        self,
        target: discord.User,
        race: str,
        old_mmr: int | None,
        new_mmr: int,
    ) -> None:
        try:
            race_emote = get_race_emote(race)
        except ValueError:
            race_emote = "🎮"

        old_str = str(old_mmr) if old_mmr is not None else "N/A"

        super().__init__(
            title="✅ MMR Updated",
            description=(
                f"**User:** {target.mention} (`{target.name}` / `{target.id}`)\n"
                f"**Race:** {race_emote} `{race}`\n"
                f"**Old MMR:** `{old_str}`\n"
                f"**New MMR:** `{new_mmr}`"
            ),
            color=discord.Color.green(),
        )


# =========================================================================
# Replay  (merged from replay_embed.py)
# =========================================================================


class ReplaySuccessEmbed(discord.Embed):
    """Full replay details embed shown after a successful replay parse."""

    def __init__(
        self,
        replay_data: dict[str, Any],
        verification_results: dict[str, Any] | None = None,
        enforcement_enabled: bool = True,
        auto_resolved: bool = False,
    ) -> None:
        p1_name: str = replay_data.get("player_1_name", "Player 1")
        p2_name: str = replay_data.get("player_2_name", "Player 2")
        p1_race_str: str = replay_data.get("player_1_race", "")
        p2_race_str: str = replay_data.get("player_2_race", "")
        winner_result: int = replay_data.get("result_int", 0)
        map_name: str = replay_data.get("map_name", "Unknown")
        duration_seconds: int = replay_data.get("game_duration_seconds", 0)
        observers: list[str] = replay_data.get("observers", [])

        p1_race_emote = get_race_emote(p1_race_str)
        p2_race_emote = get_race_emote(p2_race_str)

        if winner_result == 1:
            winner_text = f"🥇 {p1_race_emote} {p1_name}"
        elif winner_result == 2:
            winner_text = f"🥇 {p2_race_emote} {p2_name}"
        else:
            winner_text = "⚖️ Draw"

        minutes, seconds = divmod(duration_seconds, 60)
        duration_text = f"{minutes:02d}:{seconds:02d}"

        observers_text = (
            "⚠️ " + ", ".join(observers) if observers else "✅ No observers present"
        )

        map_display = map_name.replace(" (", "\n(", 1) if "(" in map_name else map_name

        super().__init__(
            title="📄 Replay Details",
            description="Summary of the uploaded replay for the match.",
            color=discord.Color.light_grey(),
        )

        self.add_field(name="", value="\u3164", inline=False)

        self.add_field(
            name="⚔️ Matchup",
            value=f"**{p1_race_emote} {p1_name}** vs\n**{p2_race_emote} {p2_name}**",
            inline=True,
        )
        self.add_field(name="🏆 Result", value=winner_text, inline=True)
        self.add_field(name="🗺️ Map", value=map_display, inline=True)

        replay_date_raw = replay_data.get("replay_time") or replay_data.get(
            "replay_date", ""
        )
        start_display = to_display(raw=replay_date_raw)
        if start_display != "—":
            self.add_field(
                name="🕒 Game Start Time",
                value=start_display,
                inline=True,
            )

        self.add_field(name="🕒 Game Duration", value=duration_text, inline=True)
        self.add_field(name="🔍 Observers", value=observers_text, inline=True)

        self.add_field(name="", value="\u3164", inline=False)

        if verification_results:
            verification_text = format_verification(
                verification_results,
                enforcement_enabled=enforcement_enabled,
                auto_resolved=auto_resolved,
            )
            self.add_field(
                name="☑️ Replay Verification",
                value=verification_text,
                inline=False,
            )


class ReplayErrorEmbed(discord.Embed):
    """Red error embed for a replay parsing failure."""

    def __init__(self, error_message: str) -> None:
        super().__init__(
            title="❌ Replay Parsing Failed",
            description=(
                "The uploaded file could not be parsed as a valid SC2Replay.\n"
                "Please try again with a different file."
            ),
            color=discord.Color.red(),
        )
        self.add_field(
            name="Error Details",
            value=f"```{error_message[:1000]}```",
            inline=False,
        )


def format_verification(
    results: dict[str, Any],
    enforcement_enabled: bool = True,
    auto_resolved: bool = False,
) -> str:
    lines: list[str] = []

    races_check = results.get("races", {})
    if races_check.get("success"):
        lines.append("- ✅ **Races Match:** Played races correspond to queued races.")
    else:
        expected = ", ".join(sorted(races_check.get("expected_races", [])))
        played = ", ".join(sorted(races_check.get("played_races", [])))
        lines.append(
            f"- ❌ **Races Mismatch:** Expected `{expected}`, but played `{played}`."
        )

    map_check = results.get("map", {})
    if map_check.get("success"):
        lines.append("- ✅ **Map Matches:** Correct map was used.")
    else:
        lines.append(
            f"- ❌ **Map Mismatch:** Expected `{map_check.get('expected_map')}`, "
            f"but played `{map_check.get('played_map')}`."
        )

    mod_check = results.get("mod", {})
    prefix = "✅" if mod_check.get("success") else "❌"
    lines.append(
        f"- {prefix} **{'Mod Valid' if mod_check.get('success') else 'Mod Invalid'}:** "
        f"{mod_check.get('message', '')}"
    )

    ts_check = results.get("timestamp", {})
    if ts_check.get("success"):
        diff = ts_check.get("time_difference_minutes")
        if diff is not None:
            lines.append(
                f"- ✅ **Timestamp Valid:** Match started within "
                f"{abs(diff):.1f} min of assignment."
            )
    else:
        if ts_check.get("error"):
            lines.append(
                f"- ❌ **Timestamp Invalid:** Could not verify. "
                f"Reason: `{ts_check['error']}`"
            )
        else:
            diff = ts_check.get("time_difference_minutes")
            if diff is not None:
                if diff < 0:
                    lines.append(
                        f"- ❌ **Timestamp Invalid:** Match started "
                        f"{abs(diff):.1f} min **before** assignment."
                    )
                else:
                    lines.append(
                        f"- ❌ **Timestamp Invalid:** Match started "
                        f"{diff:.1f} min **after** assignment (exceeds window)."
                    )
            else:
                lines.append("- ❌ **Timestamp Invalid:** Unknown error.")

    obs_check = results.get("observers", {})
    if obs_check.get("success"):
        lines.append("- ✅ **No Observers:** No unauthorized observers detected.")
    else:
        names = ", ".join(obs_check.get("observers_found", []))
        lines.append(f"- ❌ **Observers Detected:** Unauthorized observers: `{names}`.")

    for key, label in (
        ("game_privacy", "Game Privacy Setting"),
        ("game_speed", "Game Speed Setting"),
        ("game_duration", "Game Duration Setting"),
        ("locked_alliances", "Locked Alliances Setting"),
    ):
        chk = results.get(key, {})
        if chk.get("success"):
            lines.append(f"- ✅ **{label}:** `{chk.get('found')}`")
        else:
            lines.append(
                f"- ❌ **{label}:** Expected `{chk.get('expected')}`, "
                f"but found `{chk.get('found')}`."
            )

    ai_check = results.get("ai_players", {})
    if ai_check:
        if not ai_check.get("ai_detected", False):
            lines.append("- ✅ **No AI Players:** Both players are human.")
        elif ai_check.get("success"):
            lines.append(
                f"- ⚠️ **AI Player Detected:** Allowed (ALLOW_AI_PLAYERS = {ALLOW_AI_PLAYERS})."
            )
        else:
            names = ", ".join(ai_check.get("ai_player_names", []))
            lines.append(
                f"- ❌ **AI Player Detected:** ALLOW_AI_PLAYERS = {ALLOW_AI_PLAYERS}; "
                f"an AI player was detected (`{names}`)."
            )

    all_ok = all(
        results.get(k, {}).get("success", False)
        for k in (
            "races",
            "map",
            "mod",
            "timestamp",
            "observers",
            "game_privacy",
            "game_speed",
            "game_duration",
            "locked_alliances",
            "ai_players",
        )
    )
    critical_failed = not races_check.get("success", True)

    lines.append("")

    if auto_resolved:
        lines.append(
            "✅ **Verification Complete:** All critical checks passed.\n"
            "✅ **Match auto-resolved** from replay data. No manual reporting needed."
        )
    elif all_ok:
        lines.append(
            "✅ **Verification Complete:** All checks passed.\n"
            "ℹ️ This embed is provided for informational purposes only. "
            "Please report the match result manually.\n"
            "🔓 Match reporting unlocked. Please report the result "
            "**using the dropdown menus above.**"
        )
    elif critical_failed and enforcement_enabled:
        lines.append(
            "❌ **Critical Validation Failure:**\n"
            "❌ We do not accept games played with the incorrect races, map, or mod.\n"
            "🔒 Result reporting has been locked. "
            "Please contact an admin to nullify this match."
        )
    else:
        action = (
            "🔓 Match reporting unlocked. Please report the result "
            "**using the dropdown menus above.**"
            if not (enforcement_enabled and critical_failed)
            else "🔒 Result reporting has been locked."
        )
        lines.append(
            "⚠️ **Verification Issues:** One or more checks failed.\n"
            "⚠️ Please review the issues above.\n" + action
        )

    return "\n".join(lines)
