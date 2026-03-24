"""
All Discord embed classes used across bot commands and event handlers.

Organized by domain.  Private helper functions used only by embed constructors
live next to the embeds that depend on them.
"""

import json
import time
from datetime import datetime, timedelta
from typing import Any

import discord

from bot.core.config import (
    ALLOW_AI_PLAYERS,
    COERCE_INDETERMINATE_AS_LOSS,
    CONFIRMATION_TIMEOUT,
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
from bot.helpers.embed_branding import apply_default_embed_footer
from bot.helpers.emotes import (
    get_flag_emote,
    get_game_emote,
    get_globe_emote,
    get_race_emote,
    get_rank_emote,
)
from common.i18n import LOCALE_DISPLAY_NAMES, t
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
from common.lookups.race_lookups import (
    get_bw_race_codes,
    get_race_by_code,
    get_sc2_race_codes,
)
from common.lookups.region_lookups import (
    get_game_region_by_code,
    get_game_server_by_code,
    get_geographic_region_by_code,
)


# =========================================================================
# Localized display helpers
# =========================================================================


def _localized_country(code: str, locale: str = "enUS") -> str:
    """Return ``(XX) Localized Name`` for embed display values."""
    translated = t(f"country.{code}.name", locale)
    name = translated if translated != f"country.{code}.name" else code
    return f"({code}) {name}"


def _localized_region(code: str, locale: str = "enUS") -> str:
    """Return ``(XXX) Localized Name`` for embed display values."""
    translated = t(f"region.{code}.name", locale)
    name = translated if translated != f"region.{code}.name" else code
    return f"({code}) {name}"


def _localized_language(code: str) -> str:
    """Return ``(code) Display Name`` for embed display values."""
    entry = LOCALE_DISPLAY_NAMES.get(code)
    name = entry[0] if entry else code
    return f"({code}) {name}"


# =========================================================================
# Generic
# =========================================================================


class ErrorEmbed(discord.Embed):
    """Standard red error embed used across all commands."""

    def __init__(self, title: str, description: str, *, locale: str = "enUS") -> None:
        super().__init__(
            title=title,
            description=description,
            color=discord.Color.red(),
        )

        apply_default_embed_footer(self, locale=locale)


class UnsupportedGameModeEmbed(discord.Embed):
    def __init__(self, game_mode: str, locale: str = "enUS") -> None:
        super().__init__(
            title=t("unsupported_game_mode_embed.title.1", locale),
            description=t(
                "unsupported_game_mode_embed.description.1", locale, game_mode=game_mode
            ),
            color=discord.Color.orange(),
        )

        apply_default_embed_footer(self, locale=locale)


# =========================================================================
# Queue / Match lifecycle  (queue_command + ws_listener + replay_handler)
# =========================================================================

_NUMBER_EMOTES = [":one:", ":two:", ":three:", ":four:"]


def _race_display(race_code: str, locale: str = "enUS") -> str:
    return t(f"race.{race_code}.name", locale)


def _get_map_game(map_name: str) -> str:
    """Return 'bw' or 'sc2' for a map by looking it up in both map pools."""
    for mode in ("1v1", "2v2"):
        maps = get_maps(game_mode=mode, season=CURRENT_SEASON) or {}
        map_data = maps.get(map_name)
        if map_data:
            return map_data.get("game", "sc2")
    return "sc2"


def _report_display(report: str, locale: str = "enUS") -> str:
    key = f"match_result.{report}"
    result = t(key, locale)
    # If no translation found, key is returned as-is; fall back to the raw code
    return result if result != key else report


def _server_display(server_code: str, locale: str = "enUS") -> str:
    """Format server code to 'Localized Server Name (Localized Region Name)'."""
    server = get_game_server_by_code(server_code)
    if not server:
        return server_code
    raw_server = t(f"game_server.{server['code']}.name", locale)
    server_name = (
        raw_server
        if raw_server != f"game_server.{server['code']}.name"
        else server["name"]
    )
    region_code = server["game_region_code"]
    raw_region = t(f"game_region.{region_code}.name", locale)
    region_name = (
        raw_region if raw_region != f"game_region.{region_code}.name" else region_code
    )
    return f"{server_name} ({region_name})"


def _lobby_setting_display(value: str, locale: str = "enUS") -> str:
    """Return the localized display string for a lobby setting value (e.g. "Yes", "Faster")."""
    key = f"match_info_embed.lobby_setting.{value.lower()}"
    result = t(key, locale)
    return result if result != key else value


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


class QueueSetupEmbed1v1(discord.Embed):
    """Queue setup configuration display."""

    def __init__(
        self,
        bw_race: str | None,
        sc2_race: str | None,
        map_vetoes: list[str],
        locale: str = "enUS",
    ) -> None:
        super().__init__(
            title=t("queue_setup_embed.title.1", locale),
            color=discord.Color.blue(),
        )

        self.add_field(
            name=t("queue_setup_embed.field_name.1", locale),
            value=t(
                "queue_setup_embed.field_value.1", locale, quickstart_url=QUICKSTART_URL
            ),
            inline=False,
        )

        race_lines: list[str] = []
        if bw_race:
            race_lines.append(
                f"- {t('shared.game_name.brood_war', locale)}: {get_race_emote(bw_race)} {_race_display(bw_race, locale)}"
            )
        if sc2_race:
            race_lines.append(
                f"- {t('shared.game_name.starcraft_ii', locale)}: {get_race_emote(sc2_race)} {_race_display(sc2_race, locale)}"
            )
        race_value = (
            "\n".join(race_lines)
            if race_lines
            else t("queue_setup_embed.race_value_none.1", locale)
        )
        self.add_field(
            name=t("queue_setup_embed.field_name.2", locale),
            value=race_value,
            inline=False,
        )

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
            veto_value = t("queue_setup_embed.veto_value_none.1", locale)
        self.add_field(
            name=t(
                "queue_setup_embed.field_name.3",
                locale,
                veto_count=str(veto_count),
                max_map_vetoes=str(MAX_MAP_VETOES),
            ),
            value=veto_value,
            inline=False,
        )

        apply_default_embed_footer(self, locale=locale)


class MatchConfirmedEmbed(discord.Embed):
    def __init__(self, match_id: int, locale: str = "enUS") -> None:
        super().__init__(
            title=t("match_confirmed_embed.title.1", locale, match_id=str(match_id)),
            description=t("match_confirmed_embed.description.1", locale),
            color=discord.Color.gold(),
        )

        apply_default_embed_footer(self, locale=locale)


class MatchAbortAckEmbed(discord.Embed):
    def __init__(self, locale: str = "enUS") -> None:
        super().__init__(
            title=t("match_abort_ack_embed.title.1", locale),
            description=t("match_abort_ack_embed.description.1", locale),
            color=discord.Color.red(),
        )

        apply_default_embed_footer(self, locale=locale)


class QueueSearchingEmbed(discord.Embed):
    def __init__(
        self,
        stats: dict | None = None,
        *,
        match_found: bool = False,
        locale: str = "enUS",
    ) -> None:
        bw_only = stats.get("bw_only", 0) if stats else 0
        sc2_only = stats.get("sc2_only", 0) if stats else 0
        both = stats.get("both", 0) if stats else 0
        now = time.time()
        next_search = int((now // 60 + 1) * 60)

        if match_found:
            description = t("queue_searching_embed.description.2", locale)
        else:
            description = t(
                "queue_searching_embed.description.1",
                locale,
                next_search_ts=f"<t:{next_search}:R>",
                bw_only=str(bw_only),
                sc2_only=str(sc2_only),
                both=str(both),
            )

        super().__init__(
            title=t("queue_searching_embed.title.1", locale),
            description=description,
            color=discord.Color.blue(),
        )

        if match_found:
            self.add_field(
                name=t("queue_searching_embed.field_name.1", locale),
                value=t("queue_searching_embed.field_value.1", locale),
                inline=False,
            )

        apply_default_embed_footer(self, locale=locale)


class QueueSearchingEmbed2v2(discord.Embed):
    """Searching embed for 2v2 queue with 7-category composition breakdown."""

    def __init__(
        self,
        stats: dict | None = None,
        *,
        match_found: bool = False,
        locale: str = "enUS",
    ) -> None:
        now = time.time()
        next_search = int((now // 60 + 1) * 60)

        if match_found:
            description = t("queue_searching_embed.description.2", locale)
        else:
            total = stats.get("total", 0) if stats else 0
            bw_only = stats.get("bw_only", 0) if stats else 0
            mixed_only = stats.get("mixed_only", 0) if stats else 0
            sc2_only = stats.get("sc2_only", 0) if stats else 0
            bw_mixed = stats.get("bw_mixed", 0) if stats else 0
            bw_sc2 = stats.get("bw_sc2", 0) if stats else 0
            mixed_sc2 = stats.get("mixed_sc2", 0) if stats else 0
            all_three = stats.get("all_three", 0) if stats else 0
            description = (
                "The queue is searching for a 2v2 game.\n\n"
                f"- Next search: <t:{next_search}:R>\n"
                "- Search interval: 60 seconds\n"
                f"- Teams queueing: **{total}**\n"
                f"  - BW only: {bw_only}\n"
                f"  - Mixed only: {mixed_only}\n"
                f"  - SC2 only: {sc2_only}\n"
                f"  - BW + Mixed: {bw_mixed}\n"
                f"  - BW + SC2: {bw_sc2}\n"
                f"  - Mixed + SC2: {mixed_sc2}\n"
                f"  - All: {all_three}"
            )

        super().__init__(
            title=t("queue_searching_embed.title.1", locale),
            description=description,
            color=discord.Color.blue(),
        )

        if match_found:
            self.add_field(
                name=t("queue_searching_embed.field_name.1", locale),
                value=t("queue_searching_embed.field_value.1", locale),
                inline=False,
            )

        apply_default_embed_footer(self, locale=locale)


class QueueErrorEmbed(discord.Embed):
    def __init__(self, error: str, locale: str = "enUS") -> None:
        super().__init__(
            title=t("queue_error_embed.title.1", locale),
            description=error,
            color=discord.Color.red(),
        )

        apply_default_embed_footer(self, locale=locale)


class QueueJoinActivityNotifyEmbed(discord.Embed):
    """Anonymous DM when another user joins the queue (queue_join_activity WS)."""

    def __init__(self, *, game_mode: str, locale: str = "enUS") -> None:
        gm = game_mode.lower().replace("-", "_")
        mode_key = f"shared.ladder_mode.{gm}"
        mode_label = t(mode_key, locale)
        if mode_label == mode_key:
            mode_label = game_mode.upper() if gm == "ffa" else game_mode
        super().__init__(
            title=t("queue_join_activity_notify_embed.title.1", locale),
            description=t(
                "queue_join_activity_notify_embed.description.1",
                locale,
                mode_label=mode_label,
            ),
            color=discord.Color.blue(),
        )

        apply_default_embed_footer(self, locale=locale)


class NotifyMeSuccessEmbed(discord.Embed):
    """Shown after /notifyme succeeds."""

    def __init__(
        self,
        enabled: bool,
        cooldown_minutes: int | None = None,
        locale: str = "enUS",
    ) -> None:
        state = t(
            "notifyme_command.state.on.1"
            if enabled
            else "notifyme_command.state.off.1",
            locale,
        )
        cooldown_line = (
            t(
                "notifyme_command.cooldown_line.1",
                locale,
                minutes=str(cooldown_minutes),
            )
            if cooldown_minutes is not None
            else ""
        )
        description = t(
            "notifyme_command.success.1",
            locale,
            state=state,
            cooldown_line=cooldown_line,
        )
        super().__init__(
            title=t("notifyme_success_embed.title.1", locale),
            description=description,
            color=discord.Color.green() if enabled else discord.Color.light_grey(),
        )
        apply_default_embed_footer(self, locale=locale)


class MatchFoundEmbed(discord.Embed):
    def __init__(self, match_data: dict, locale: str = "enUS") -> None:
        match_id = match_data.get("id", "?")
        super().__init__(
            title=t("match_found_embed.title.1", locale, match_id=str(match_id)),
            description=t("match_found_embed.description.1", locale),
            color=discord.Color.green(),
        )
        assigned_at = ensure_utc(match_data.get("assigned_at"))
        if assigned_at is not None:
            deadline_dt = assigned_at + timedelta(seconds=CONFIRMATION_TIMEOUT)
            deadline_str = to_discord_timestamp(dt=deadline_dt, style="R")
        else:
            deadline_str = "—"
        self.add_field(
            name=t("match_found_embed.field_name.deadline", locale),
            value=t(
                "match_found_embed.field_value.deadline", locale, deadline=deadline_str
            ),
            inline=False,
        )

        apply_default_embed_footer(self, locale=locale)


class MatchWaitingConfirmEmbed(discord.Embed):
    def __init__(self, match_id: int, locale: str = "enUS") -> None:
        super().__init__(
            title=t(
                "match_waiting_confirm_embed.title.1", locale, match_id=str(match_id)
            ),
            description=t("match_waiting_confirm_embed.description.1", locale),
            color=discord.Color.green(),
        )

        apply_default_embed_footer(self, locale=locale)


class MatchInfoEmbed1v1(discord.Embed):
    """Full match details embed matching the alpha UI layout."""

    def __init__(
        self,
        match_data: dict,
        p1_info: dict[str, Any] | None = None,
        p2_info: dict[str, Any] | None = None,
        pending_report: str | None = None,
        replay_uploaded: bool = False,
        locale: str = "enUS",
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

        p1_rank_emote = get_rank_emote(match_data.get("player_1_letter_rank", "U"))
        p2_rank_emote = get_rank_emote(match_data.get("player_2_letter_rank", "U"))

        p1_race_emote = get_race_emote(p1_race) if p1_race else ""
        p2_race_emote = get_race_emote(p2_race) if p2_race else ""

        title = (
            f"{t('match_info_embed.title.1', locale, match_id=str(match_id))}\n"
            f"{p1_rank_emote} {p1_flag} {p1_race_emote} {p1_name} ({p1_mmr}) "
            f"vs "
            f"{p2_rank_emote} {p2_flag} {p2_race_emote} {p2_name} ({p2_mmr})"
        )

        super().__init__(title=title, description="", color=discord.Color.teal())

        self.add_field(name="", value="", inline=False)

        p1_race_name = _race_display(p1_race, locale) if p1_race else "Unknown"
        p2_race_name = _race_display(p2_race, locale) if p2_race else "Unknown"

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

        discord_label = t("match_info_embed.player_line.discord", locale)
        battletag_label = t("match_info_embed.player_line.battletag", locale)
        aka_label = t("match_info_embed.player_line.aka", locale)

        p1_line = (
            f"- {p1_rank_emote} {p1_flag} {p1_race_emote} {p1_name} ({p1_race_name})"
        )
        p1_line += f"\n  - {discord_label}: {p1_discord_username} ({p1_uid})"
        if p1_battletag:
            p1_line += f"\n  - {battletag_label}: `{p1_battletag}`"
        if p1_alts:
            p1_line += f"\n  - ({aka_label} {', '.join(p1_alts)})"

        p2_line = (
            f"- {p2_rank_emote} {p2_flag} {p2_race_emote} {p2_name} ({p2_race_name})"
        )
        p2_line += f"\n  - {discord_label}: {p2_discord_username} ({p2_uid})"
        if p2_battletag:
            p2_line += f"\n  - {battletag_label}: `{p2_battletag}`"
        if p2_alts:
            p2_line += f"\n  - ({aka_label} {', '.join(p2_alts)})"

        self.add_field(
            name=t("match_info_embed.field_name.1", locale),
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

        server_full = _server_display(server_code, locale)

        self.add_field(
            name=t("match_info_embed.field_name.2", locale),
            value=t(
                "match_info_embed.field_value.2",
                locale,
                map_name=map_info["name"] if map_info else map_name,
                map_link=map_link,
                map_author=map_author,
                mod_name=mod_name,
                mod_link=mod_link,
                mod_author=mod_author,
            ),
            inline=False,
        )

        self.add_field(name="", value="", inline=False)

        self.add_field(
            name=t("match_info_embed.field_name.3", locale),
            value=t(
                "match_info_embed.field_value.3",
                locale,
                server=server_full,
                locked_alliances=_lobby_setting_display(
                    EXPECTED_LOBBY_SETTINGS["locked_alliances"], locale
                ),
            ),
            inline=True,
        )

        self.add_field(
            name="\u3164",
            value=t(
                "match_info_embed.field_value.4",
                locale,
                privacy=_lobby_setting_display(
                    EXPECTED_LOBBY_SETTINGS["privacy"], locale
                ),
                speed=_lobby_setting_display(EXPECTED_LOBBY_SETTINGS["speed"], locale),
                duration=_lobby_setting_display(
                    EXPECTED_LOBBY_SETTINGS["duration"], locale
                ),
            ),
            inline=True,
        )

        self.add_field(name="", value="", inline=False)
        self.add_field(name="", value="", inline=False)

        if pending_report is not None:
            result_value = t(
                "match_info_embed.field_value_pending.4",
                locale,
                result=_report_display(pending_report, locale),
            )
        else:
            result_value = t("match_info_embed.field_value_none.4", locale)
        self.add_field(
            name=t("match_info_embed.field_name.4", locale),
            value=result_value,
            inline=True,
        )

        replay_value = (
            t("match_info_embed.field_value_uploaded.5", locale)
            if replay_uploaded
            else t("match_info_embed.field_value_no_replay.5", locale)
        )
        self.add_field(
            name=t("match_info_embed.field_name.5", locale),
            value=replay_value,
            inline=True,
        )

        if ENABLE_REPLAY_VALIDATION and not replay_uploaded:
            footer_text = t("match_info_embed.footer.1", locale)
        else:
            footer_text = t("match_info_embed.footer.2", locale)
        self.set_footer(text=footer_text)

        apply_default_embed_footer(self, locale=locale)


class MatchAbortedEmbed(discord.Embed):
    def __init__(
        self,
        match_data: dict,
        p1_info: dict[str, Any] | None = None,
        p2_info: dict[str, Any] | None = None,
        locale: str = "enUS",
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
            get_rank_emote(match_data.get("player_1_letter_rank", "U")),
            get_flag_emote(p1_country),
            get_race_emote(p1_race) if p1_race else "",
            p1_name,
            p1_mmr,
        )
        p2_hdr = _player_header(
            get_rank_emote(match_data.get("player_2_letter_rank", "U")),
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
            title=t(
                "match_aborted_embed.title.1",
                locale,
                match_id=str(match_id),
                game_mode="1v1",
            ),
            description=f"{p1_hdr} vs {p2_hdr}",
            color=discord.Color.red(),
        )
        self.add_field(
            name=t("shared.field_name.mmr_changes", locale),
            value=f"- {p1_name}: `+0 ({p1_mmr})`\n- {p2_name}: `+0 ({p2_mmr})`",
            inline=False,
        )
        self.add_field(
            name=t("shared.field_name.reason", locale),
            value=t("match_aborted_embed.field_value.2", locale, aborter=aborter),
            inline=False,
        )

        apply_default_embed_footer(self, locale=locale)


class MatchAbandonedEmbed(discord.Embed):
    def __init__(
        self,
        match_data: dict,
        p1_info: dict[str, Any] | None = None,
        p2_info: dict[str, Any] | None = None,
        locale: str = "enUS",
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
            get_rank_emote(match_data.get("player_1_letter_rank", "U")),
            get_flag_emote(p1_country),
            get_race_emote(p1_race) if p1_race else "",
            p1_name,
            p1_mmr,
        )
        p2_hdr = _player_header(
            get_rank_emote(match_data.get("player_2_letter_rank", "U")),
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
            title=t(
                "match_abandoned_embed.title.1",
                locale,
                match_id=str(match_id),
                game_mode="1v1",
            ),
            description=f"{p1_hdr} vs {p2_hdr}",
            color=discord.Color.red(),
        )
        self.add_field(
            name=t("shared.field_name.mmr_changes", locale),
            value=f"- {p1_name}: `+0 ({p1_mmr})`\n- {p2_name}: `+0 ({p2_mmr})`",
            inline=False,
        )
        self.add_field(
            name=t("shared.field_name.reason", locale),
            value=t("match_abandoned_embed.field_value.2", locale, abandoner=abandoner),
            inline=False,
        )

        apply_default_embed_footer(self, locale=locale)


class MatchFinalizedEmbed(discord.Embed):
    def __init__(
        self,
        match_data: dict,
        p1_info: dict[str, Any] | None = None,
        p2_info: dict[str, Any] | None = None,
        locale: str = "enUS",
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
        p1_rank = get_rank_emote(match_data.get("player_1_letter_rank", "U"))
        p2_rank = get_rank_emote(match_data.get("player_2_letter_rank", "U"))
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
            title=t(
                "match_finalized_embed.title.1",
                locale,
                match_id=str(match_id),
                game_mode="1v1",
            ),
            description=f"{p1_hdr} vs {p2_hdr}",
            color=discord.Color.gold(),
        )

        if result == "draw":
            result_value = t("shared.result_draw", locale)
        elif result == "player_1_win":
            result_value = f"🏆 {p1_rank} {p1_flag} {p1_race_emote} {p1_name}"
        else:
            result_value = f"🏆 {p2_rank} {p2_flag} {p2_race_emote} {p2_name}"

        p1_sign = "+" if p1_change >= 0 else ""
        p2_sign = "+" if p2_change >= 0 else ""

        self.add_field(
            name=t("shared.field_name.result", locale), value=result_value, inline=True
        )
        self.add_field(
            name=t("shared.field_name.mmr_changes", locale),
            value=(
                f"- {p1_name}: `{p1_sign}{p1_change} ({p1_mmr} → {p1_new})`\n"
                f"- {p2_name}: `{p2_sign}{p2_change} ({p2_mmr} → {p2_new})`"
            ),
            inline=True,
        )

        apply_default_embed_footer(self, locale=locale)


class MatchConflictEmbed(discord.Embed):
    def __init__(
        self,
        match_data: dict,
        p1_info: dict[str, Any] | None = None,
        p2_info: dict[str, Any] | None = None,
        locale: str = "enUS",
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
            get_rank_emote(match_data.get("player_1_letter_rank", "U")),
            get_flag_emote(p1_country),
            get_race_emote(p1_race) if p1_race else "",
            p1_name,
            p1_mmr,
        )
        p2_hdr = _player_header(
            get_rank_emote(match_data.get("player_2_letter_rank", "U")),
            get_flag_emote(p2_country),
            get_race_emote(p2_race) if p2_race else "",
            p2_name,
            p2_mmr,
        )

        p1_report = match_data.get("player_1_report", "?")
        p2_report = match_data.get("player_2_report", "?")

        super().__init__(
            title=t(
                "match_conflict_embed.title.1",
                locale,
                match_id=str(match_id),
                game_mode="1v1",
            ),
            description=f"{p1_hdr} vs {p2_hdr}",
            color=discord.Color.orange(),
        )
        self.add_field(
            name=t("shared.field_name.reports", locale),
            value=(
                f"- {p1_name}: `{_report_display(p1_report, locale)}`\n"
                f"- {p2_name}: `{_report_display(p2_report, locale)}`"
            ),
            inline=False,
        )
        self.add_field(
            name=t("shared.field_name.reason", locale),
            value=t("match_conflict_embed.field_value.2", locale),
            inline=False,
        )

        apply_default_embed_footer(self, locale=locale)


# =========================================================================
# Queue / Match lifecycle  (2v2)
# =========================================================================


def _team_header_2v2(
    match_data: dict,
    team: str,
    player_infos: dict[int, dict[str, Any] | None] | None = None,
    new_mmr: int | str | None = None,
    show_mmr: bool = True,
    locale: str = "enUS",
) -> str:
    """Return '{rank} {flag} {race} P1 & {flag} {race} P2 [(MMR)]' for a 2v2 team."""
    player_infos = player_infos or {}
    p1_uid = match_data.get(f"{team}_player_1_discord_uid")
    p2_uid = match_data.get(f"{team}_player_2_discord_uid")
    p1_name = match_data.get(f"{team}_player_1_name", "Player 1")
    p2_name = match_data.get(f"{team}_player_2_name", "Player 2")
    p1_race = match_data.get(f"{team}_player_1_race", "")
    p2_race = match_data.get(f"{team}_player_2_race", "")
    mmr = match_data.get(f"{team}_mmr", "?")

    p1_info = player_infos.get(p1_uid) if p1_uid else None
    p2_info = player_infos.get(p2_uid) if p2_uid else None
    p1_country = (p1_info.get("nationality") or "XX") if p1_info else "XX"
    p2_country = (p2_info.get("nationality") or "XX") if p2_info else "XX"
    p1_flag = get_flag_emote(p1_country)
    p2_flag = get_flag_emote(p2_country)

    rank_emote = get_rank_emote(match_data.get(f"{team}_letter_rank", "U"))
    p1_race_emote = get_race_emote(p1_race) if p1_race else ""
    p2_race_emote = get_race_emote(p2_race) if p2_race else ""

    if not show_mmr:
        return (
            f"{rank_emote} {p1_flag} {p1_race_emote} **{p1_name}** & "
            f"{p2_flag} {p2_race_emote} **{p2_name}**"
        )
    mmr_part = f"({mmr} → {new_mmr})" if new_mmr is not None else f"({mmr})"
    return (
        f"{rank_emote} {p1_flag} {p1_race_emote} **{p1_name}** & "
        f"{p2_flag} {p2_race_emote} **{p2_name}** {mmr_part}"
    )


class QueueSetupEmbed2v2(discord.Embed):
    """Queue setup for 2v2: shows all three composition selections."""

    def __init__(
        self,
        pure_bw_leader_race: str | None,
        pure_bw_member_race: str | None,
        mixed_leader_race: str | None,
        mixed_member_race: str | None,
        pure_sc2_leader_race: str | None,
        pure_sc2_member_race: str | None,
        map_vetoes: list[str],
        leader_player_name: str = "Leader",
        member_player_name: str = "Member",
        locale: str = "enUS",
    ) -> None:
        super().__init__(
            title="2v2 Queue Setup",
            color=discord.Color.blurple(),
        )

        def _comp_value(leader_race: str | None, member_race: str | None) -> str:
            if leader_race and member_race:
                lr_emote = get_race_emote(leader_race)
                mr_emote = get_race_emote(member_race)
                return (
                    f"- {leader_player_name}: {lr_emote} {_race_display(leader_race, locale)}\n"
                    f"- {member_player_name}: {mr_emote} {_race_display(member_race, locale)}"
                )
            return "—"

        self.add_field(
            name="Pure BW",
            value=_comp_value(pure_bw_leader_race, pure_bw_member_race),
            inline=False,
        )
        self.add_field(
            name="Mixed",
            value=_comp_value(mixed_leader_race, mixed_member_race),
            inline=False,
        )
        self.add_field(
            name="Pure SC2",
            value=_comp_value(pure_sc2_leader_race, pure_sc2_member_race),
            inline=False,
        )

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
            veto_value = t("queue_setup_embed.veto_value_none.1", locale)
        self.add_field(
            name=t(
                "queue_setup_embed.field_name.3",
                locale,
                veto_count=str(veto_count),
                max_map_vetoes=str(MAX_MAP_VETOES),
            ),
            value=veto_value,
            inline=False,
        )

        apply_default_embed_footer(self, locale=locale)


class MatchInfoEmbeds2v2(list[discord.Embed]):
    """Two-embed list for a 2v2 match: [players embed, details embed]."""

    def __init__(
        self,
        match_data: dict,
        player_infos: dict[int, dict[str, Any] | None] | None = None,
        pending_report: str | None = None,
        replay_uploaded: bool = False,
        locale: str = "enUS",
    ) -> None:
        player_infos = player_infos or {}
        match_id = match_data.get("id", "?")
        map_name = match_data.get("map_name", "Unknown")
        server_code = match_data.get("server_name", "Unknown")

        t1_hdr = _team_header_2v2(match_data, "team_1", player_infos, locale=locale)
        t2_hdr = _team_header_2v2(match_data, "team_2", player_infos, locale=locale)

        # --- Embed 1: title + teams + player details ---
        title = t("match_info_embed_2v2.title.1", locale, match_id=str(match_id))
        description = f"{t1_hdr}\nvs\n{t2_hdr}"
        embed1 = discord.Embed(
            title=title, description=description, color=discord.Color.teal()
        )

        embed1.add_field(name="", value="", inline=False)

        # Team player details
        t1_p1_uid = match_data.get("team_1_player_1_discord_uid")
        t1_p2_uid = match_data.get("team_1_player_2_discord_uid")
        t2_p1_uid = match_data.get("team_2_player_1_discord_uid")
        t2_p2_uid = match_data.get("team_2_player_2_discord_uid")

        discord_label = t("match_info_embed.player_line.discord", locale)
        battletag_label = t("match_info_embed.player_line.battletag", locale)
        aka_label = t("match_info_embed.player_line.aka", locale)

        def _player_detail(uid: int | None, name: str, race: str) -> str:
            info: dict[str, Any] | None = player_infos.get(uid) if uid else None
            country = (info.get("nationality") or "XX") if info else "XX"
            flag = get_flag_emote(country)
            race_emote = get_race_emote(race) if race else ""
            race_name = (
                _race_display(race, locale) if race else t("shared.unknown", locale)
            )
            discord_username = (
                info.get("discord_username", "Unknown") if info else "Unknown"
            )
            battletag = (info.get("battletag") or None) if info else None
            alts = (info.get("alt_player_names") or []) if info else []

            line = f"- {flag} {race_emote} {name} ({race_name})"
            line += f"\n  - {discord_label}: {discord_username} ({uid})"
            if battletag:
                line += f"\n  - {battletag_label}: `{battletag}`"
            if alts:
                line += f"\n  - ({aka_label} {', '.join(alts)})"
            return line

        t1_lines = (
            _player_detail(
                t1_p1_uid,
                match_data.get("team_1_player_1_name", "?"),
                match_data.get("team_1_player_1_race", ""),
            )
            + "\n"
            + _player_detail(
                t1_p2_uid,
                match_data.get("team_1_player_2_name", "?"),
                match_data.get("team_1_player_2_race", ""),
            )
        )
        t2_lines = (
            _player_detail(
                t2_p1_uid,
                match_data.get("team_2_player_1_name", "?"),
                match_data.get("team_2_player_1_race", ""),
            )
            + "\n"
            + _player_detail(
                t2_p2_uid,
                match_data.get("team_2_player_2_name", "?"),
                match_data.get("team_2_player_2_race", ""),
            )
        )

        embed1.add_field(
            name=t("match_info_embed_2v2.team.1", locale),
            value=t1_lines,
            inline=True,
        )
        embed1.add_field(
            name=t("match_info_embed_2v2.team.2", locale),
            value=t2_lines,
            inline=True,
        )

        # --- Embed 2: map, lobby settings, report, replay ---
        embed2 = discord.Embed(description="", color=discord.Color.teal())

        map_info = get_map_by_short_name(map_name)
        map_author = map_info["author"] if map_info else "Unknown"
        map_link = _get_map_link(map_name, server_code)

        mod = get_mod_by_code("multi")
        mod_name = mod["name"] if mod else "SC: Evo Complete"
        mod_author = mod["author"] if mod else "SCEvoDev"
        mod_link = _get_mod_link(server_code)

        server_full = _server_display(server_code, locale)

        embed2.add_field(
            name=t("match_info_embed.field_name.2", locale),
            value=t(
                "match_info_embed.field_value.2",
                locale,
                map_name=map_info["name"] if map_info else map_name,
                map_link=map_link,
                map_author=map_author,
                mod_name=mod_name,
                mod_link=mod_link,
                mod_author=mod_author,
            ),
            inline=False,
        )

        embed2.add_field(name="", value="", inline=False)

        embed2.add_field(
            name=t("match_info_embed.field_name.3", locale),
            value=t(
                "match_info_embed.field_value.3",
                locale,
                server=server_full,
                locked_alliances=_lobby_setting_display(
                    EXPECTED_LOBBY_SETTINGS["locked_alliances"], locale
                ),
            ),
            inline=True,
        )

        embed2.add_field(
            name="\u3164",
            value=t(
                "match_info_embed.field_value.4",
                locale,
                privacy=_lobby_setting_display(
                    EXPECTED_LOBBY_SETTINGS["privacy"], locale
                ),
                speed=_lobby_setting_display(EXPECTED_LOBBY_SETTINGS["speed"], locale),
                duration=_lobby_setting_display(
                    EXPECTED_LOBBY_SETTINGS["duration"], locale
                ),
            ),
            inline=True,
        )

        embed2.add_field(name="", value="", inline=False)
        embed2.add_field(name="", value="", inline=False)

        if pending_report is not None:
            result_value = t(
                "match_info_embed_2v2.field_value_pending.4",
                locale,
                result=_report_display(pending_report, locale),
            )
        else:
            result_value = t("match_info_embed.field_value_none.4", locale)
        embed2.add_field(
            name=t("match_info_embed.field_name.4", locale),
            value=result_value,
            inline=True,
        )

        replay_value = (
            t("match_info_embed.field_value_uploaded.5", locale)
            if replay_uploaded
            else t("match_info_embed.field_value_no_replay.5", locale)
        )
        embed2.add_field(
            name=t("match_info_embed.field_name.5", locale),
            value=replay_value,
            inline=True,
        )

        if ENABLE_REPLAY_VALIDATION and not replay_uploaded:
            footer_text = t("match_info_embed.footer.1", locale)
        else:
            footer_text = t("match_info_embed.footer.2", locale)
        embed2.set_footer(text=footer_text)

        apply_default_embed_footer(embed2, locale=locale)

        super().__init__([embed1, embed2])


class MatchAbortedEmbed2v2(discord.Embed):
    def __init__(
        self,
        match_data: dict,
        player_infos: dict[int, dict[str, Any] | None] | None = None,
        locale: str = "enUS",
    ) -> None:
        match_id = match_data.get("id", "?")
        t1_mmr = match_data.get("team_1_mmr", "?")
        t2_mmr = match_data.get("team_2_mmr", "?")
        t1_hdr = _team_header_2v2(match_data, "team_1", player_infos, locale=locale)
        t2_hdr = _team_header_2v2(match_data, "team_2", player_infos, locale=locale)

        super().__init__(
            title=t(
                "match_aborted_embed.title.1",
                locale,
                match_id=str(match_id),
                game_mode="2v2",
            ),
            description=f"{t1_hdr}\nvs\n{t2_hdr}",
            color=discord.Color.red(),
        )
        self.add_field(
            name=t("shared.field_name.mmr_changes", locale),
            value=(f"- Team 1: `+0 ({t1_mmr})`\n- Team 2: `+0 ({t2_mmr})`"),
            inline=False,
        )
        self.add_field(
            name=t("shared.field_name.reason", locale),
            value=t("match_aborted_embed_2v2.field_value.1", locale),
            inline=False,
        )
        apply_default_embed_footer(self, locale=locale)


class MatchAbandonedEmbed2v2(discord.Embed):
    def __init__(
        self,
        match_data: dict,
        player_infos: dict[int, dict[str, Any] | None] | None = None,
        locale: str = "enUS",
    ) -> None:
        match_id = match_data.get("id", "?")
        t1_mmr = match_data.get("team_1_mmr", "?")
        t2_mmr = match_data.get("team_2_mmr", "?")
        t1_hdr = _team_header_2v2(match_data, "team_1", player_infos, locale=locale)
        t2_hdr = _team_header_2v2(match_data, "team_2", player_infos, locale=locale)

        super().__init__(
            title=t(
                "match_abandoned_embed.title.1",
                locale,
                match_id=str(match_id),
                game_mode="2v2",
            ),
            description=f"{t1_hdr}\nvs\n{t2_hdr}",
            color=discord.Color.red(),
        )
        self.add_field(
            name=t("shared.field_name.mmr_changes", locale),
            value=(f"- Team 1: `+0 ({t1_mmr})`\n- Team 2: `+0 ({t2_mmr})`"),
            inline=False,
        )
        self.add_field(
            name=t("shared.field_name.reason", locale),
            value=t("match_abandoned_embed_2v2.field_value.1", locale),
            inline=False,
        )
        apply_default_embed_footer(self, locale=locale)


class MatchFinalizedEmbed2v2(discord.Embed):
    def __init__(
        self,
        match_data: dict,
        player_infos: dict[int, dict[str, Any] | None] | None = None,
        locale: str = "enUS",
    ) -> None:
        match_id = match_data.get("id", "?")
        result = match_data.get("match_result", "unknown")
        t1_mmr = match_data.get("team_1_mmr", 0)
        t2_mmr = match_data.get("team_2_mmr", 0)
        t1_change = match_data.get("team_1_mmr_change") or 0
        t2_change = match_data.get("team_2_mmr_change") or 0
        t1_new = t1_mmr + t1_change
        t2_new = t2_mmr + t2_change
        t1_hdr = _team_header_2v2(
            match_data, "team_1", player_infos, new_mmr=t1_new, locale=locale
        )
        t2_hdr = _team_header_2v2(
            match_data, "team_2", player_infos, new_mmr=t2_new, locale=locale
        )

        super().__init__(
            title=t(
                "match_finalized_embed.title.1",
                locale,
                match_id=str(match_id),
                game_mode="2v2",
            ),
            description=f"{t1_hdr}\nvs\n{t2_hdr}",
            color=discord.Color.gold(),
        )

        if result == "draw":
            result_value = t("shared.result_draw", locale)
        elif result == "team_1_win":
            t1_hdr_short = _team_header_2v2(
                match_data, "team_1", player_infos, show_mmr=False, locale=locale
            )
            result_value = f"🏆 {t1_hdr_short}"
        else:
            t2_hdr_short = _team_header_2v2(
                match_data, "team_2", player_infos, show_mmr=False, locale=locale
            )
            result_value = f"🏆 {t2_hdr_short}"

        t1_sign = "+" if t1_change >= 0 else ""
        t2_sign = "+" if t2_change >= 0 else ""

        self.add_field(
            name=t("shared.field_name.result", locale),
            value=result_value,
            inline=True,
        )
        self.add_field(
            name=t("shared.field_name.mmr_changes", locale),
            value=(
                f"- Team 1: `{t1_sign}{t1_change} ({t1_mmr} → {t1_new})`\n"
                f"- Team 2: `{t2_sign}{t2_change} ({t2_mmr} → {t2_new})`"
            ),
            inline=True,
        )
        apply_default_embed_footer(self, locale=locale)


class MatchConflictEmbed2v2(discord.Embed):
    def __init__(
        self,
        match_data: dict,
        player_infos: dict[int, dict[str, Any] | None] | None = None,
        locale: str = "enUS",
    ) -> None:
        match_id = match_data.get("id", "?")
        t1_hdr = _team_header_2v2(match_data, "team_1", player_infos, locale=locale)
        t2_hdr = _team_header_2v2(match_data, "team_2", player_infos, locale=locale)
        t1_report = match_data.get("team_1_report", "?")
        t2_report = match_data.get("team_2_report", "?")

        super().__init__(
            title=t(
                "match_conflict_embed.title.1",
                locale,
                match_id=str(match_id),
                game_mode="2v2",
            ),
            description=f"{t1_hdr}\nvs\n{t2_hdr}",
            color=discord.Color.orange(),
        )
        self.add_field(
            name=t("shared.field_name.reports", locale),
            value=(
                f"- Team 1: `{_report_display(t1_report, locale)}`\n"
                f"- Team 2: `{_report_display(t2_report, locale)}`"
            ),
            inline=False,
        )
        self.add_field(
            name=t("shared.field_name.reason", locale),
            value=t("match_conflict_embed_2v2.field_value.1", locale),
            inline=False,
        )
        apply_default_embed_footer(self, locale=locale)


# =========================================================================
# Setup
# =========================================================================


class SetupIntroEmbed(discord.Embed):
    def __init__(self, locale: str = "enUS") -> None:
        super().__init__(
            title=t("setup_intro_embed.title.1", locale),
            description=t("setup_intro_embed.description.1", locale),
            color=discord.Color.blue(),
        )

        apply_default_embed_footer(self, locale=locale)


class SetupValidationErrorEmbed(discord.Embed):
    def __init__(self, title: str, error: str, locale: str = "enUS") -> None:
        super().__init__(
            title=f"❌ {title}",
            description=t(
                "setup_validation_error_embed.description.1", locale, error=error
            ),
            color=discord.Color.red(),
        )

        apply_default_embed_footer(self, locale=locale)


class SetupSelectionEmbed(discord.Embed):
    def __init__(
        self,
        country: Country | None = None,
        region: GeographicRegion | None = None,
        language: str | None = None,
        locale: str = "enUS",
    ) -> None:
        super().__init__(
            title=t("setup_selection_embed.title.1", locale),
            color=discord.Color.blue(),
        )
        selected_lines: list[str] = []
        if country:
            selected_lines.append(
                t(
                    "setup_selection_embed.nationality_label.1",
                    locale,
                    flag=str(get_flag_emote(country["code"])),
                    name=_localized_country(country["code"], locale),
                )
            )
        if region:
            selected_lines.append(
                t(
                    "setup_selection_embed.location_label.1",
                    locale,
                    globe=str(get_globe_emote(region["globe_emote_code"])),
                    name=_localized_region(region["code"], locale),
                )
            )
        if language:
            entry = LOCALE_DISPLAY_NAMES.get(language)
            flag = entry[1] if entry else ""
            selected_lines.append(
                t(
                    "setup_selection_embed.language_label.1",
                    locale,
                    flag=flag,
                    name=_localized_language(language),
                )
            )

        if selected_lines:
            selected_block = (
                t("setup_selection_embed.selected_header.1", locale)
                + "\n"
                + "\n".join(selected_lines)
                + "\n\n"
            )
        else:
            selected_block = ""

        if country and region and language:
            self.description = selected_block + t(
                "setup_selection_embed.confirm_prompt.1", locale
            )
        else:
            missing: list[str] = []
            if not country:
                missing.append(t("setup_selection_embed.missing.nationality", locale))
            if not region:
                missing.append(t("setup_selection_embed.missing.location", locale))
            if not language:
                missing.append(t("setup_selection_embed.missing.language", locale))
            self.description = (
                selected_block
                + t(
                    "setup_selection_embed.select_prompt.1",
                    locale,
                    missing=", ".join(missing),
                )
                + "\n\n"
                + t("setup_selection_embed.country_limit_note.1", locale)
            )

        apply_default_embed_footer(self, locale=locale)


class SetupPreviewEmbed(discord.Embed):
    def __init__(
        self,
        player_name: str,
        battletag: str,
        alt_ids: list[str],
        country: Country,
        region: GeographicRegion,
        language: str,
        locale: str = "enUS",
    ) -> None:
        super().__init__(
            title=t("setup_preview_embed.title.1", locale),
            description=t("setup_preview_embed.description.1", locale),
            color=discord.Color.blue(),
        )
        self.add_field(
            name=t("shared.field_name.user_id", locale),
            value=f"`{player_name}`",
            inline=False,
        )
        self.add_field(
            name=t("shared.field_name.battletag", locale),
            value=f"`{battletag}`",
            inline=False,
        )
        self.add_field(
            name=t(
                "shared.field_name.nationality",
                locale,
                flag=str(get_flag_emote(country["code"])),
            ),
            value=f"`{_localized_country(country['code'], locale)}`",
            inline=False,
        )
        self.add_field(
            name=t(
                "shared.field_name.location",
                locale,
                globe=str(get_globe_emote(region["globe_emote_code"])),
            ),
            value=f"`{_localized_region(region['code'], locale)}`",
            inline=False,
        )
        self.add_field(
            name=t("shared.field_name.language", locale),
            value=f"`{_localized_language(language)}`",
            inline=False,
        )
        alt_display = ", ".join(f"`{a}`" for a in alt_ids) if alt_ids else "`None`"
        self.add_field(
            name=t("shared.field_name.alt_ids", locale),
            value=alt_display,
            inline=False,
        )

        apply_default_embed_footer(self, locale=locale)


class SetupSuccessEmbed(discord.Embed):
    def __init__(
        self,
        player_name: str,
        battletag: str,
        alt_ids: list[str],
        country: Country,
        region: GeographicRegion,
        language: str,
        locale: str = "enUS",
    ) -> None:
        super().__init__(
            title=t("setup_success_embed.title.1", locale),
            description=t("setup_success_embed.description.1", locale),
            color=discord.Color.green(),
        )
        self.add_field(
            name=t("shared.field_name.user_id", locale),
            value=f"`{player_name}`",
            inline=False,
        )
        self.add_field(
            name=t("shared.field_name.battletag", locale),
            value=f"`{battletag}`",
            inline=False,
        )
        self.add_field(
            name=t(
                "shared.field_name.nationality",
                locale,
                flag=str(get_flag_emote(country["code"])),
            ),
            value=f"`{_localized_country(country['code'], locale)}`",
            inline=False,
        )
        self.add_field(
            name=t(
                "shared.field_name.location",
                locale,
                globe=str(get_globe_emote(region["globe_emote_code"])),
            ),
            value=f"`{_localized_region(region['code'], locale)}`",
            inline=False,
        )
        self.add_field(
            name=t("shared.field_name.language", locale),
            value=f"`{_localized_language(language)}`",
            inline=False,
        )
        alt_display = ", ".join(f"`{a}`" for a in alt_ids) if alt_ids else "`None`"
        self.add_field(
            name=t("shared.field_name.alt_ids", locale),
            value=alt_display,
            inline=False,
        )

        apply_default_embed_footer(self, locale=locale)


# =========================================================================
# Profile
# =========================================================================


def _sort_profile_mmrs(mmrs: list[dict], canonical_races: list[str]) -> list[dict]:
    """Order MMR rows by static race order (matches queue / leaderboard)."""

    rank = {code: i for i, code in enumerate(canonical_races)}
    tail = len(canonical_races)

    def sort_key(m: dict) -> tuple[int, str]:
        race = m.get("race") or ""
        return (rank.get(race, tail), race)

    return sorted(mmrs, key=sort_key)


def _format_mmr_rows(mmrs: list[dict], locale: str = "enUS") -> str:
    lines: list[str] = []
    for m in mmrs:
        race_code: str = m.get("race") or ""
        race_name = _race_display(race_code, locale)

        try:
            race_emote = get_race_emote(race_code)
        except ValueError:
            race_emote = "🎮"

        rank_letter = m.get("letter_rank") or "U"
        try:
            rank_emote = get_rank_emote(str(rank_letter))
        except ValueError:
            rank_emote = get_rank_emote("U")

        gp: int = m.get("games_played") or 0
        gw: int = m.get("games_won") or 0
        gl: int = m.get("games_lost") or 0
        gd: int = m.get("games_drawn") or 0
        mmr_val: int = m.get("mmr") or 0
        wr = (gw / gp * 100) if gp > 0 else 0.0

        if gp == 0:
            line = t(
                "profile_embed.mmr_row_unranked.1",
                locale,
                rank_emote=str(rank_emote),
                race_emote=str(race_emote),
                race_name=race_name,
            )
            lines.append(line)
            continue

        line = t(
            "profile_embed.mmr_row.1",
            locale,
            rank_emote=str(rank_emote),
            race_emote=str(race_emote),
            race_name=race_name,
            mmr_val=str(mmr_val),
            gw=str(gw),
            gl=str(gl),
            gd=str(gd),
            wr=f"{wr:.1f}",
        )

        recent: dict = m.get("recent") or {}
        for period_key, tr_key in (
            ("14d", "profile_embed.recent_stats_14d.1"),
            ("30d", "profile_embed.recent_stats_30d.1"),
            ("90d", "profile_embed.recent_stats_90d.1"),
        ):
            st: dict = recent.get(period_key) or {}
            w = int(st.get("games_won", 0))
            lo = int(st.get("games_lost", 0))
            d = int(st.get("games_drawn", 0))
            tot = int(st.get("games_played", w + lo + d))
            wr_p = (w / tot * 100) if tot > 0 else 0.0
            line += "\n" + t(
                tr_key,
                locale,
                w=str(w),
                l=str(lo),
                d=str(d),
                wr=f"{wr_p:.1f}",
            )

        last_played = m.get("last_played_at")
        if last_played and gp > 0:
            ts = to_discord_timestamp(raw=last_played, style="f")
            if ts != "—":
                line += "\n" + t("profile_embed.last_played.1", locale, ts=ts)

        lines.append(line)
    return "\n".join(lines)


class ProfileNotFoundEmbed(discord.Embed):
    def __init__(self, locale: str = "enUS") -> None:
        super().__init__(
            title=t("profile_not_found_embed.title.1", locale),
            description=t("profile_not_found_embed.description.1", locale),
            color=discord.Color.red(),
        )

        apply_default_embed_footer(self, locale=locale)


class ProfileEmbed(discord.Embed):
    def __init__(
        self,
        user: discord.User | discord.Member,
        player: dict,
        mmrs: list[dict],
        locale: str = "enUS",
    ) -> None:
        completed = player.get("completed_setup", False)
        color = discord.Color.green() if completed else discord.Color.orange()
        status_icon = "✅" if completed else "⚠️"
        title_name = player.get("player_name") or user.name

        super().__init__(
            title=t(
                "profile_embed.title.1",
                locale,
                status_icon=status_icon,
                title_name=title_name,
            ),
            color=color,
        )

        if user.display_avatar:
            self.set_thumbnail(url=user.display_avatar.url)

        self._add_basic_info(player, locale)
        self._add_location(player, locale)
        self._add_mmrs(mmrs, locale)
        self._add_account_status(player, locale)

        self.set_footer(
            text=t(
                "profile_embed.footer.1", locale, username=user.name, uid=str(user.id)
            )
        )

        apply_default_embed_footer(self, locale=locale)

    def _add_basic_info(self, player: dict, locale: str = "enUS") -> None:
        not_set = t("shared.not_set", locale)
        parts = [
            t(
                "profile_embed.player_name_label.1",
                locale,
                name=player.get("player_name") or not_set,
            ),
            t(
                "profile_embed.battletag_label.1",
                locale,
                battletag=player.get("battletag") or not_set,
            ),
        ]
        alt_ids: list[str] = player.get("alt_player_names") or []
        if alt_ids:
            parts.append(
                t("profile_embed.alt_ids_label.1", locale, alt_ids=", ".join(alt_ids))
            )
        self.add_field(
            name=t("profile_embed.field_name.1", locale),
            value="\n".join(parts),
            inline=False,
        )

    def _add_location(self, player: dict, locale: str = "enUS") -> None:
        parts: list[str] = []

        nationality = player.get("nationality")
        if nationality:
            country = get_country_by_code(nationality)
            if country:
                flag = get_flag_emote(nationality)
                parts.append(
                    t(
                        "profile_embed.nationality_label.1",
                        locale,
                        flag=str(flag),
                        name=_localized_country(nationality, locale),
                    )
                )

        location = player.get("location")
        if location:
            region = get_geographic_region_by_code(location)
            if region:
                globe = get_globe_emote(region["globe_emote_code"])
                parts.append(
                    t(
                        "profile_embed.location_label.1",
                        locale,
                        globe=str(globe),
                        name=_localized_region(location, locale),
                    )
                )

        language = player.get("language")
        if language:
            entry = LOCALE_DISPLAY_NAMES.get(language)
            flag = entry[1] if entry else ""
            parts.append(
                t(
                    "profile_embed.language_label.1",
                    locale,
                    flag=flag,
                    name=_localized_language(language),
                )
            )

        if parts:
            self.add_field(
                name=t("profile_embed.field_name.2", locale),
                value="\n".join(parts),
                inline=False,
            )

    def _add_mmrs(self, mmrs: list[dict], locale: str = "enUS") -> None:
        if not mmrs:
            self.add_field(
                name=t("profile_embed.mmr_field_name.1", locale),
                value=t("profile_embed.no_mmr.1", locale),
                inline=False,
            )
            return

        bw_mmrs = [m for m in mmrs if m.get("race", "").startswith("bw_")]
        sc2_mmrs = [m for m in mmrs if m.get("race", "").startswith("sc2_")]
        bw_mmrs = _sort_profile_mmrs(bw_mmrs, get_bw_race_codes())
        sc2_mmrs = _sort_profile_mmrs(sc2_mmrs, get_sc2_race_codes())

        bw_emote = get_game_emote("bw")
        sc2_emote = get_game_emote("sc2")

        if bw_mmrs:
            self.add_field(
                name=t(
                    "profile_embed.bw_mmr_field_name.1", locale, bw_emote=str(bw_emote)
                ),
                value=_format_mmr_rows(bw_mmrs, locale),
                inline=False,
            )
        if sc2_mmrs:
            self.add_field(
                name=t(
                    "profile_embed.sc2_mmr_field_name.1",
                    locale,
                    sc2_emote=str(sc2_emote),
                ),
                value=_format_mmr_rows(sc2_mmrs, locale),
                inline=False,
            )

    def _add_account_status(self, player: dict, locale: str = "enUS") -> None:
        tos = player.get("accepted_tos", False)
        setup = player.get("completed_setup", False)
        parts = [
            t("profile_embed.tos_accepted.1", locale)
            if tos
            else t("profile_embed.tos_declined.1", locale),
            t("profile_embed.setup_complete.1", locale)
            if setup
            else t("profile_embed.setup_incomplete.1", locale),
        ]
        self.add_field(
            name=t("profile_embed.field_name.3", locale),
            value="\n".join(parts),
            inline=False,
        )


# =========================================================================
# Terms of Service
# =========================================================================


class TermsOfServiceEmbed(discord.Embed):
    def __init__(self, locale: str = "enUS") -> None:
        super().__init__(
            title=t("terms_of_service_embed.title.1", locale),
            description=t(
                "terms_of_service_embed.description.1",
                locale,
                tos_url=TOS_URL,
                tos_mirror_url=TOS_MIRROR_URL,
            ),
            color=discord.Color.blue(),
        )

        apply_default_embed_footer(self, locale=locale)


class TermsOfServiceAcceptedEmbed(discord.Embed):
    def __init__(self, locale: str = "enUS") -> None:
        super().__init__(
            title=t("terms_of_service_accepted_embed.title.1", locale),
            description=t("terms_of_service_accepted_embed.description.1", locale),
            color=discord.Color.green(),
        )

        apply_default_embed_footer(self, locale=locale)


class TermsOfServiceDeclinedEmbed(discord.Embed):
    def __init__(self, locale: str = "enUS") -> None:
        super().__init__(
            title=t("terms_of_service_declined_embed.title.1", locale),
            description=t("terms_of_service_declined_embed.description.1", locale),
            color=discord.Color.red(),
        )

        apply_default_embed_footer(self, locale=locale)


# =========================================================================
# Set Country
# =========================================================================


class SetCountryNotFoundEmbed(discord.Embed):
    def __init__(self, country: str, locale: str = "enUS"):
        super().__init__(
            title=t("set_country_not_found_embed.title.1", locale),
            description=t(
                "set_country_not_found_embed.description.1",
                locale,
                country=country,
            ),
            color=discord.Color.red(),
        )

        apply_default_embed_footer(self, locale=locale)


class SetCountryPreviewEmbed(discord.Embed):
    def __init__(self, country: Country, locale: str = "enUS"):
        super().__init__(
            title=t("set_country_preview_embed.title.1", locale),
            description=t("set_country_preview_embed.description.1", locale),
            color=discord.Color.blue(),
        )
        self.add_field(
            name=t(
                "set_country_preview_embed.field_name.1",
                locale,
                flag=str(get_flag_emote(country["code"])),
            ),
            value=f"`{_localized_country(country['code'], locale)}`",
        )

        apply_default_embed_footer(self, locale=locale)


class SetCountryConfirmEmbed(discord.Embed):
    def __init__(self, country: Country, locale: str = "enUS"):
        super().__init__(
            title=t("set_country_confirm_embed.title.1", locale),
            description=t("set_country_confirm_embed.description.1", locale),
            color=discord.Color.blue(),
        )
        self.add_field(
            name=t(
                "set_country_confirm_embed.field_name.1",
                locale,
                flag=str(get_flag_emote(country["code"])),
            ),
            value=f"`{_localized_country(country['code'], locale)}`",
        )

        apply_default_embed_footer(self, locale=locale)


# =========================================================================
# Admin: Ban
# =========================================================================


class BanPreviewEmbed(discord.Embed):
    def __init__(
        self, target_discord_uid: int, target_player_name: str, locale: str = "enUS"
    ) -> None:
        super().__init__(
            title=t("ban_preview_embed.title.1", locale),
            description=t(
                "ban_preview_embed.description.1",
                locale,
                mention=f"<@{target_discord_uid}>",
                username=target_player_name,
                uid=str(target_discord_uid),
            ),
            color=discord.Color.orange(),
        )

        apply_default_embed_footer(self, locale=locale)


class BanSuccessEmbed(discord.Embed):
    def __init__(
        self,
        target_discord_uid: int,
        target_player_name: str,
        new_is_banned: bool,
        locale: str = "enUS",
    ) -> None:
        title_key = (
            "ban_success_embed.title_banned.1"
            if new_is_banned
            else "ban_success_embed.title_unbanned.1"
        )
        status_key = (
            "ban_success_embed.status_banned.1"
            if new_is_banned
            else "ban_success_embed.status_unbanned.1"
        )
        color = discord.Color.red() if new_is_banned else discord.Color.green()
        super().__init__(
            title=t(title_key, locale),
            description=t(
                "ban_success_embed.description.1",
                locale,
                mention=f"<@{target_discord_uid}>",
                username=target_player_name,
                uid=str(target_discord_uid),
                status=t(status_key, locale),
            ),
            color=color,
        )

        apply_default_embed_footer(self, locale=locale)


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


_MATCH_SNAPSHOT_NAME_LEN = 12
_MATCH_SNAPSHOT_PLAYER_FIELD_LEN = (
    20  # rank + race + ISO + padded name (monospace column)
)


def _format_match_player_snapshot(
    name: str | None,
    race_code: str | None,
    letter_rank: str | None,
    nationality: str | None,
) -> str:
    """Single player token: ``{letter} {race2} {ISO2} {name:12}`` (truncated)."""
    rank_ch = (letter_rank or "U")[:1]
    race = _race_short(race_code).ljust(2)[:2]
    nat_raw = nationality if nationality and nationality != "--" else "--"
    nat = (nat_raw[:2]).ljust(2)
    p_name = (name or "Unknown")[:_MATCH_SNAPSHOT_NAME_LEN].ljust(
        _MATCH_SNAPSHOT_NAME_LEN
    )
    return f"{rank_ch} {race} {nat} {p_name}"


def _elapsed_seconds(iso_str: str | None) -> str:
    """Convert an ISO timestamp to an elapsed-seconds string like ' 794s'."""
    dt = ensure_utc(iso_str)
    if dt is None:
        return "   ?s"
    elapsed = int((utc_now() - dt).total_seconds())
    return f"{elapsed:>4d}s"


def _format_queue_player(entry: dict) -> str:
    """Format a single queue player as a monospace backtick string.

    Format: ``{bw_rank} {bw_race} {sc2_rank} {sc2_race} {nat} {name:12}``
    where rank is the letter rank (U if unranked) or ``-`` if not queueing that
    game, and race is the 2-char short code or ``--`` if not queueing that game.
    """
    player_name = (entry.get("player_name") or "Unknown")[:12]
    name_padded = f"{player_name:<12}"

    bw_race_code = entry.get("bw_race")
    sc2_race_code = entry.get("sc2_race")
    bw_rank = entry.get("bw_letter_rank") or "U" if bw_race_code else "-"
    sc2_rank = entry.get("sc2_letter_rank") or "U" if sc2_race_code else "-"
    bw_race = _race_short(bw_race_code) if bw_race_code else "--"
    sc2_race = _race_short(sc2_race_code) if sc2_race_code else "--"
    nat = (entry.get("nationality") or "--")[:2]

    player_str = f"{bw_rank} {bw_race} {sc2_rank} {sc2_race} {nat} {name_padded}"
    wait_time = _elapsed_seconds(entry.get("joined_at"))

    return f"`{player_str}` `{wait_time}`"


def _format_blank_queue_slot() -> str:
    return f"`{' ' * 25}` `{' ' * 5}`"


def _format_match_slot(match: dict, id_width: int) -> str:
    """Format a single active match as a monospace backtick string."""
    match_id = match.get("id") or 0
    p1_block = _format_match_player_snapshot(
        match.get("player_1_name"),
        match.get("player_1_race"),
        match.get("player_1_letter_rank"),
        match.get("player_1_nationality"),
    )
    p2_block = _format_match_player_snapshot(
        match.get("player_2_name"),
        match.get("player_2_race"),
        match.get("player_2_letter_rank"),
        match.get("player_2_nationality"),
    )

    elapsed = _elapsed_seconds(match.get("assigned_at"))
    mid = f"{match_id:>{id_width}d}"

    return f"`{mid}` `{p1_block}` `vs` `{p2_block}` `{elapsed}`"


def _format_blank_match_slot(id_width: int) -> str:
    blank_id = " " * id_width
    blank_player = " " * _MATCH_SNAPSHOT_PLAYER_FIELD_LEN
    blank_time = " " * 5
    return f"`{blank_id}` `{blank_player}` `vs` `{blank_player}` `{blank_time}`"


class SystemStatsEmbed(discord.Embed):
    """Embed 1: DataFrame memory stats."""

    def __init__(self, dataframe_stats: dict, locale: str = "enUS") -> None:
        super().__init__(
            title=t("system_stats_embed.title.1", locale),
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
                name=t("system_stats_embed.field_name.1", locale),
                value=f"```\n{stats_block}\n```",
                inline=False,
            )
        else:
            self.add_field(
                name=t("system_stats_embed.field_name.1", locale),
                value=t("system_stats_embed.field_value_no_stats.1", locale),
                inline=False,
            )

        apply_default_embed_footer(self, locale=locale)


class QueueSnapshotEmbed(discord.Embed):
    """Embed 2: Queue players in monospace backtick format, two columns of 15."""

    def __init__(self, queue: list[dict], locale: str = "enUS") -> None:
        queue_size = len(queue)
        super().__init__(
            title=t("queue_snapshot_embed.title.1", locale),
            color=discord.Color.green(),
        )

        description = (
            t("queue_snapshot_embed.players_in_queue.1", locale, count=str(queue_size))
            + "\n"
        )

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
            description += f"\n_{t('shared.and_n_more', locale, n=str(queue_size - MAX_QUEUE_SLOTS))}_"

        self.description = description

        apply_default_embed_footer(self, locale=locale)


class MatchesEmbed(discord.Embed):
    """Embed 3: Active matches in monospace backtick format."""

    def __init__(self, active_matches: list[dict], locale: str = "enUS") -> None:
        match_count = len(active_matches)
        super().__init__(
            title=t("matches_embed.title.1", locale),
            color=discord.Color.orange(),
        )

        id_width = 5
        if active_matches:
            max_id = max(m.get("id") or 0 for m in active_matches)
            id_width = max(5, len(str(max_id)))

        description = (
            t("matches_embed.active_matches.1", locale, count=str(match_count)) + "\n"
        )

        for i in range(MAX_MATCH_SLOTS):
            if i < len(active_matches):
                description += _format_match_slot(active_matches[i], id_width) + "\n"
            else:
                description += _format_blank_match_slot(id_width) + "\n"

        if match_count > MAX_MATCH_SLOTS:
            description += f"\n_{t('shared.and_n_more', locale, n=str(match_count - MAX_MATCH_SLOTS))}_"

        self.description = description

        apply_default_embed_footer(self, locale=locale)


class QueueSnapshotEmbed2v2(discord.Embed):
    """2v2 queue snapshot: shows teams (parties) currently searching."""

    def __init__(self, queue: list[dict], locale: str = "enUS") -> None:
        queue_size = len(queue)
        super().__init__(
            title=t("queue_snapshot_embed_2v2.title.1", locale),
            color=discord.Color.green(),
        )
        description = (
            t(
                "queue_snapshot_embed_2v2.teams_in_queue.1",
                locale,
                count=str(queue_size),
            )
            + "\n"
        )
        for i, entry in enumerate(queue[:15]):
            leader = entry.get("player_name", "?")
            member = entry.get("party_member_name", "?")
            mmr = entry.get("team_mmr", "?")
            comps: list[str] = []
            if entry.get("pure_bw_leader_race") and entry.get("pure_bw_member_race"):
                comps.append("BW")
            if entry.get("mixed_leader_race") and entry.get("mixed_member_race"):
                comps.append("Mix")
            if entry.get("pure_sc2_leader_race") and entry.get("pure_sc2_member_race"):
                comps.append("SC2")
            comp_str = "+".join(comps) or "—"
            description += (
                f"`{i + 1:>2}` **{leader}** & **{member}** ({mmr}) [{comp_str}]\n"
            )
        if queue_size > 15:
            description += t(
                "queue_snapshot_embed_2v2.and_more.1",
                locale,
                count=str(queue_size - 15),
            )
        self.description = description
        apply_default_embed_footer(self, locale=locale)


class MatchesEmbed2v2(discord.Embed):
    """2v2 active matches snapshot."""

    def __init__(self, active_matches: list[dict], locale: str = "enUS") -> None:
        match_count = len(active_matches)
        super().__init__(
            title=t("matches_embed_2v2.title.1", locale),
            color=discord.Color.orange(),
        )
        description = (
            t("matches_embed_2v2.active_matches.1", locale, count=str(match_count))
            + "\n"
        )
        for m in active_matches[:10]:
            mid = m.get("id", "?")
            t1p1 = m.get("team_1_player_1_name", "?")
            t1p2 = m.get("team_1_player_2_name", "?")
            t2p1 = m.get("team_2_player_1_name", "?")
            t2p2 = m.get("team_2_player_2_name", "?")
            t1_mmr = m.get("team_1_mmr", "?")
            t2_mmr = m.get("team_2_mmr", "?")
            description += (
                f"`#{mid}` **{t1p1}** & **{t1p2}** ({t1_mmr}) "
                f"vs **{t2p1}** & **{t2p2}** ({t2_mmr})\n"
            )
        if match_count > 10:
            description += t(
                "parties_embed.and_more.1", locale, count=str(match_count - 10)
            )
        self.description = description
        apply_default_embed_footer(self, locale=locale)


class PartiesEmbed(discord.Embed):
    """Active 2v2 parties snapshot."""

    def __init__(self, parties: list[dict], locale: str = "enUS") -> None:
        party_count = len(parties)
        super().__init__(
            title=t("parties_embed.title.1", locale),
            color=discord.Color.purple(),
        )
        description = (
            t("parties_embed.active_parties.1", locale, count=str(party_count)) + "\n"
        )
        for p in parties[:20]:
            leader = p.get("leader_player_name", "?")
            member = p.get("member_player_name", "?")
            description += (
                t(
                    "parties_embed.roster_line.1",
                    locale,
                    leader=leader,
                    member=member,
                )
                + "\n"
            )
        if party_count > 20:
            description += t(
                "parties_embed.and_more.1", locale, count=str(party_count - 20)
            )
        self.description = description
        apply_default_embed_footer(self, locale=locale)


# =========================================================================
# Admin: Match Details
# =========================================================================


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


def _result_display(
    result: str | None, p1_name: str, p2_name: str, locale: str = "enUS"
) -> str:
    if result == "player_1_win":
        return t("result_display.player_win.1", locale, name=p1_name)
    if result == "player_2_win":
        return t("result_display.player_win.1", locale, name=p2_name)
    if result == "draw":
        return t("result_display.draw.1", locale)
    if result == "invalidated":
        return t("result_display.invalidated.1", locale)
    return t("result_display.in_progress.1", locale)


def _format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


def _admin_server_display(server_code: str | None, locale: str = "enUS") -> str:
    """Resolve server code to localized full name."""
    if not server_code:
        return t("shared.unknown", locale)
    return _server_display(server_code, locale)


class MatchNotFoundEmbed(discord.Embed):
    def __init__(self, match_id: int, locale: str = "enUS") -> None:
        super().__init__(
            title=t("match_not_found_embed.title.1", locale),
            description=t(
                "match_not_found_embed.description.1", locale, match_id=str(match_id)
            ),
            color=discord.Color.red(),
        )

        apply_default_embed_footer(self, locale=locale)


class AdminMatchEmbed(discord.Embed):
    """Main admin match overview — full matches_1v1 row data."""

    def __init__(
        self,
        match: dict[str, Any],
        player_1: dict[str, Any] | None,
        player_2: dict[str, Any] | None,
        admin: dict[str, Any] | None,
        locale: str = "enUS",
    ) -> None:
        match_id = match.get("id", "?")
        result = match.get("match_result")

        if result is None:
            color = discord.Color.blue()
        elif result == "invalidated":
            color = discord.Color.dark_grey()
        else:
            color = discord.Color.green()

        p1_name = match.get("player_1_name") or t("shared.unknown", locale)
        p2_name = match.get("player_2_name") or t("shared.unknown", locale)
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
            title=t("admin_match_embed.title.1", locale, match_id=str(match_id)),
            description=t(
                "admin_match_embed.description.1",
                locale,
                p1_prefix=p1_prefix,
                p1_name=p1_name,
                p1_mmr=str(p1_mmr),
                p2_prefix=p2_prefix,
                p2_name=p2_name,
                p2_mmr=str(p2_mmr),
            ),
            color=color,
        )

        self.add_field(
            name="",
            value=t(
                "admin_match_embed.field_value.overview",
                locale,
                display=_result_display(result, p1_name, p2_name, locale),
                p1_uid=str(p1_uid),
                p2_uid=str(p2_uid),
            ),
            inline=False,
        )

        p1_report_code = match.get("player_1_report")
        p2_report_code = match.get("player_2_report")
        p1_report = t(f"match_result.{p1_report_code or 'no_report'}", locale)
        p2_report = t(f"match_result.{p2_report_code or 'no_report'}", locale)
        reports_text = t(
            "admin_match_embed.field_value.reports",
            locale,
            p1_name=p1_name,
            p1_report=p1_report,
            p2_name=p2_name,
            p2_report=p2_report,
        )

        admin_intervened = match.get("admin_intervened", False)
        if admin_intervened:
            admin_uid = match.get("admin_discord_uid")
            admin_username = admin.get("discord_username") if admin else None
            if admin_username:
                resolved_text = t(
                    "admin_match_embed.resolved_yes_with_name",
                    locale,
                    admin_username=admin_username,
                    admin_uid=str(admin_uid),
                )
            else:
                resolved_text = t(
                    "admin_match_embed.resolved_yes_no_name",
                    locale,
                    admin_uid=str(admin_uid),
                )
        else:
            resolved_text = t("admin_match_embed.resolved_no", locale)

        self.add_field(
            name=t("admin_match_embed.field_name.reports", locale),
            value=reports_text,
            inline=True,
        )
        self.add_field(
            name=t("admin_match_embed.field_name.resolved", locale),
            value=resolved_text,
            inline=True,
        )

        p1_change = match.get("player_1_mmr_change")
        p2_change = match.get("player_2_mmr_change")
        if p1_change is not None or p2_change is not None:
            p1_c = p1_change or 0
            p2_c = p2_change or 0
            p1_new = p1_mmr + p1_c
            p2_new = p2_mmr + p2_c
            mmr_text = t(
                "admin_match_embed.field_value.mmr_changes",
                locale,
                p1_name=p1_name,
                p1_change=f"{p1_c:+d}",
                p1_mmr=str(p1_mmr),
                p1_new=str(p1_new),
                p2_name=p2_name,
                p2_change=f"{p2_c:+d}",
                p2_mmr=str(p2_mmr),
                p2_new=str(p2_new),
            )
            self.add_field(
                name=t("admin_match_embed.field_name.mmr_changes", locale),
                value=mmr_text,
                inline=False,
            )

        map_name = match.get("map_name") or t("shared.unknown", locale)
        server_code = match.get("server_name")
        info_text = t(
            "admin_match_embed.match_info.map_server",
            locale,
            map_name=map_name,
            server=_admin_server_display(server_code, locale),
        )
        info_text += t(
            "admin_match_embed.match_info.assigned",
            locale,
            ts=to_discord_timestamp(raw=match.get("assigned_at")),
        )
        if match.get("completed_at"):
            info_text += t(
                "admin_match_embed.match_info.completed",
                locale,
                ts=to_discord_timestamp(raw=match.get("completed_at")),
            )
        self.add_field(
            name=t("admin_match_embed.field_name.match_info", locale),
            value=info_text,
            inline=False,
        )

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
            name=t("admin_match_embed.field_name.raw", locale),
            value=f"```json\n{raw_json}\n```",
            inline=False,
        )

        p1_replay = match.get("player_1_replay_path")
        p2_replay = match.get("player_2_replay_path")
        p1_status = (
            t("admin_match_embed.replay_uploaded", locale)
            if p1_replay
            else t("admin_match_embed.replay_no", locale)
        )
        p2_status = (
            t("admin_match_embed.replay_uploaded", locale)
            if p2_replay
            else t("admin_match_embed.replay_no", locale)
        )
        replay_text = t(
            "admin_match_embed.field_value.replay_status",
            locale,
            p1_name=p1_name,
            p1_status=p1_status,
            p2_name=p2_name,
            p2_status=p2_status,
        )
        self.add_field(
            name=t("admin_match_embed.field_name.replay_status", locale),
            value=replay_text,
            inline=False,
        )

        apply_default_embed_footer(self, locale=locale)


class AdminReplayDetailsEmbed(discord.Embed):
    """Per-player replay details — mirrors the player-facing ReplaySuccessEmbed
    format with full verification."""

    def __init__(
        self,
        player_num: int,
        replay: dict[str, Any],
        verification: dict[str, Any] | None,
        replay_url: str | None,
        locale: str = "enUS",
    ) -> None:
        super().__init__(
            title=t(
                "admin_replay_details_embed.title.1", locale, player_num=str(player_num)
            ),
            description=t("admin_replay_details_embed.description.1", locale),
            color=discord.Color.light_grey(),
        )

        p1_name = replay.get("player_1_name") or t("shared.player_fallback.1", locale)
        p2_name = replay.get("player_2_name") or t("shared.player_fallback.2", locale)
        p1_race = replay.get("player_1_race") or ""
        p2_race = replay.get("player_2_race") or ""
        result_str = replay.get("match_result") or "?"
        map_name = replay.get("map_name") or t("shared.unknown", locale)
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
            result_display = t(
                "admin_replay_details_embed.winner_p1.1",
                locale,
                race_emote=str(p1_emote),
                name=p1_name,
            )
        elif result_str in ("player_2_win", "2"):
            result_display = t(
                "admin_replay_details_embed.winner_p2.1",
                locale,
                race_emote=str(p2_emote),
                name=p2_name,
            )
        elif result_str in ("draw", "0"):
            result_display = t("replay_success_embed.winner_draw.1", locale)
        else:
            result_display = str(result_str)

        map_display = map_name.replace(" (", "\n(", 1) if "(" in map_name else map_name

        self.add_field(name="", value="\u3164", inline=False)

        self.add_field(
            name=t("shared.field_name.matchup", locale),
            value=f"**{p1_emote} {p1_name}** vs\n**{p2_emote} {p2_name}**",
            inline=True,
        )
        self.add_field(
            name=t("shared.field_name.result_header", locale),
            value=result_display,
            inline=True,
        )
        self.add_field(
            name=t("shared.field_name.map", locale), value=map_display, inline=True
        )

        start_time = to_display(raw=replay.get("replay_time"))
        self.add_field(
            name=t("shared.field_name.game_start_time", locale),
            value=start_time,
            inline=True,
        )
        self.add_field(
            name=t("shared.field_name.game_duration", locale),
            value=_format_duration(duration),
            inline=True,
        )

        obs_text = (
            f"⚠️ {', '.join(observers)}"
            if observers
            else t("format_verification.observers_ok.1", locale)
        )
        self.add_field(
            name=t("shared.field_name.observers", locale), value=obs_text, inline=True
        )

        self.add_field(name="", value="\u3164", inline=False)

        if verification:
            self.add_field(
                name=t("shared.field_name.replay_verification", locale),
                value=format_verification(
                    verification, enforcement_enabled=False, locale=locale
                ),
                inline=False,
            )

        if replay_url:
            self.add_field(
                name=t("admin_replay_details_embed.field_name.7", locale),
                value=t(
                    "admin_replay_details_embed.field_value.7",
                    locale,
                    replay_url=replay_url,
                ),
                inline=False,
            )

        apply_default_embed_footer(self, locale=locale)


class AdminMatchEmbed2v2(discord.Embed):
    """Admin match overview for a 2v2 match — 4 players / 2 teams."""

    def __init__(
        self,
        match: dict[str, Any],
        players: dict[str, dict[str, Any] | None],
        admin: dict[str, Any] | None,
        locale: str = "enUS",
    ) -> None:
        match_id = match.get("id", "?")
        result = match.get("match_result")

        if result is None:
            color = discord.Color.blue()
        elif result == "invalidated":
            color = discord.Color.dark_grey()
        else:
            color = discord.Color.green()

        t1_mmr = match.get("team_1_mmr") or 0
        t2_mmr = match.get("team_2_mmr") or 0

        super().__init__(
            title=t("admin_match_embed_2v2.title.1", locale, match_id=str(match_id)),
            description=t(
                "admin_match_embed_2v2.description.1",
                locale,
                t1_mmr=str(t1_mmr),
                t2_mmr=str(t2_mmr),
            ),
            color=color,
        )

        # --- Team rosters ---
        roster_lines: list[str] = []
        for team_num in (1, 2):
            roster_lines.append(f"**Team {team_num}:**")
            for player_num in (1, 2):
                key = f"team_{team_num}_player_{player_num}"
                name = match.get(f"{key}_name") or t("shared.unknown", locale)
                race = match.get(f"{key}_race") or ""
                p = players.get(key)
                nat = p.get("nationality") if p else None
                prefix = _player_prefix(race, nat)
                roster_lines.append(f"- {prefix} **{name}**")
        self.add_field(
            name=t("admin_match_embed_2v2.field_name.team_rosters", locale),
            value="\n".join(roster_lines),
            inline=False,
        )

        # --- Result overview ---
        display = _result_display_2v2(result, locale)
        self.add_field(
            name="",
            value=t(
                "admin_match_embed_2v2.field_value.overview",
                locale,
                display=display,
                t1_p1_uid=str(match.get("team_1_player_1_discord_uid") or 0),
                t1_p2_uid=str(match.get("team_1_player_2_discord_uid") or 0),
                t2_p1_uid=str(match.get("team_2_player_1_discord_uid") or 0),
                t2_p2_uid=str(match.get("team_2_player_2_discord_uid") or 0),
            ),
            inline=False,
        )

        # --- Reports ---
        t1_report_code = match.get("team_1_report")
        t2_report_code = match.get("team_2_report")
        t1_report = t(f"match_result.{t1_report_code or 'no_report'}", locale)
        t2_report = t(f"match_result.{t2_report_code or 'no_report'}", locale)
        self.add_field(
            name=t("admin_match_embed_2v2.field_name.reports", locale),
            value=t(
                "admin_match_embed_2v2.field_value.reports",
                locale,
                t1_report=t1_report,
                t2_report=t2_report,
            ),
            inline=True,
        )

        # --- Admin resolved ---
        admin_intervened = match.get("admin_intervened", False)
        if admin_intervened:
            admin_uid = match.get("admin_discord_uid")
            admin_username = admin.get("discord_username") if admin else None
            if admin_username:
                resolved_text = t(
                    "admin_match_embed.resolved_yes_with_name",
                    locale,
                    admin_username=admin_username,
                    admin_uid=str(admin_uid),
                )
            else:
                resolved_text = t(
                    "admin_match_embed.resolved_yes_no_name",
                    locale,
                    admin_uid=str(admin_uid),
                )
        else:
            resolved_text = t("admin_match_embed.resolved_no", locale)

        self.add_field(
            name=t("admin_match_embed.field_name.resolved", locale),
            value=resolved_text,
            inline=True,
        )

        # --- MMR changes ---
        t1_change = match.get("team_1_mmr_change")
        t2_change = match.get("team_2_mmr_change")
        if t1_change is not None or t2_change is not None:
            t1_c = t1_change or 0
            t2_c = t2_change or 0
            t1_new = t1_mmr + t1_c
            t2_new = t2_mmr + t2_c
            mmr_text = t(
                "admin_match_embed_2v2.field_value.mmr_changes",
                locale,
                t1_change=f"{t1_c:+d}",
                t1_mmr=str(t1_mmr),
                t1_new=str(t1_new),
                t2_change=f"{t2_c:+d}",
                t2_mmr=str(t2_mmr),
                t2_new=str(t2_new),
            )
            self.add_field(
                name=t("admin_match_embed.field_name.mmr_changes", locale),
                value=mmr_text,
                inline=False,
            )

        # --- Match info ---
        map_name = match.get("map_name") or t("shared.unknown", locale)
        server_code = match.get("server_name")
        info_text = t(
            "admin_match_embed.match_info.map_server",
            locale,
            map_name=map_name,
            server=_admin_server_display(server_code, locale),
        )
        info_text += t(
            "admin_match_embed.match_info.assigned",
            locale,
            ts=to_discord_timestamp(raw=match.get("assigned_at")),
        )
        if match.get("completed_at"):
            info_text += t(
                "admin_match_embed.match_info.completed",
                locale,
                ts=to_discord_timestamp(raw=match.get("completed_at")),
            )
        self.add_field(
            name=t("admin_match_embed.field_name.match_info", locale),
            value=info_text,
            inline=False,
        )

        # --- Raw JSON ---
        raw: dict[str, Any] = {}
        for key in (
            "id",
            "team_1_player_1_discord_uid",
            "team_1_player_2_discord_uid",
            "team_2_player_1_discord_uid",
            "team_2_player_2_discord_uid",
            "team_1_player_1_name",
            "team_1_player_2_name",
            "team_2_player_1_name",
            "team_2_player_2_name",
            "team_1_player_1_race",
            "team_1_player_2_race",
            "team_2_player_1_race",
            "team_2_player_2_race",
            "team_1_mmr",
            "team_2_mmr",
            "team_1_report",
            "team_2_report",
            "match_result",
            "team_1_mmr_change",
            "team_2_mmr_change",
            "map_name",
            "server_name",
            "assigned_at",
            "completed_at",
            "admin_intervened",
            "admin_discord_uid",
            "team_1_replay_path",
            "team_1_replay_row_id",
            "team_1_uploaded_at",
            "team_2_replay_path",
            "team_2_replay_row_id",
            "team_2_uploaded_at",
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
            name=t("admin_match_embed.field_name.raw", locale),
            value=f"```json\n{raw_json}\n```",
            inline=False,
        )

        # --- Replay status ---
        t1_replay = match.get("team_1_replay_path")
        t2_replay = match.get("team_2_replay_path")
        t1_status = (
            t("admin_match_embed.replay_uploaded", locale)
            if t1_replay
            else t("admin_match_embed.replay_no", locale)
        )
        t2_status = (
            t("admin_match_embed.replay_uploaded", locale)
            if t2_replay
            else t("admin_match_embed.replay_no", locale)
        )
        self.add_field(
            name=t("admin_match_embed.field_name.replay_status", locale),
            value=t(
                "admin_match_embed_2v2.field_value.replay_status",
                locale,
                t1_status=t1_status,
                t2_status=t2_status,
            ),
            inline=False,
        )

        apply_default_embed_footer(self, locale=locale)


def _result_display_2v2(result: str | None, locale: str = "enUS") -> str:
    if result == "team_1_win":
        return t("result_display.team_1_win.1", locale)
    if result == "team_2_win":
        return t("result_display.team_2_win.1", locale)
    if result == "draw":
        return t("result_display.draw.1", locale)
    if result == "invalidated":
        return t("result_display.invalidated.1", locale)
    return t("result_display.in_progress.1", locale)


# =========================================================================
# Admin: Resolve
# =========================================================================


def _get_result_display(result: str, data: dict, locale: str = "enUS") -> str:
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
        return t(
            "get_result_display.player_1_win.1",
            locale,
            p1_emote=str(p1_emote),
            p1_name=p1_name,
        )
    elif result == "player_2_win":
        return t(
            "get_result_display.player_2_win.1",
            locale,
            p2_emote=str(p2_emote),
            p2_name=p2_name,
        )
    elif result == "draw":
        return t("get_result_display.draw.1", locale)
    elif result == "invalidated":
        return t("get_result_display.invalidated.1", locale)
    return result


class ResolvePreviewEmbed(discord.Embed):
    def __init__(
        self,
        match_id: int,
        result: str,
        result_display: str,
        reason: str | None,
        locale: str = "enUS",
    ) -> None:
        description = t(
            "resolve_preview_embed.description.1",
            locale,
            match_id=str(match_id),
            result_display=result_display,
            result=result,
        )
        if reason:
            description += t(
                "resolve_preview_embed.reason_suffix.1", locale, reason=reason
            )
        description += t("resolve_preview_embed.confirm_suffix.1", locale)
        super().__init__(
            title=t("resolve_preview_embed.title.1", locale),
            description=description,
            color=discord.Color.orange(),
        )

        apply_default_embed_footer(self, locale=locale)


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
        locale: str = "enUS",
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

        color = discord.Color.green() if is_admin_confirm else discord.Color.gold()
        title_key = (
            "admin_resolution_embed.title_confirm.1"
            if is_admin_confirm
            else "admin_resolution_embed.title_player.1"
        )

        super().__init__(
            title=t(title_key, locale, match_id=str(match_id)),
            description=t(
                "admin_resolution_embed.description.1",
                locale,
                p1_prefix=p1_prefix,
                p1_name=p1_name,
                p1_old=str(p1_old),
                p1_new=str(p1_new),
                p2_prefix=p2_prefix,
                p2_name=p2_name,
                p2_old=str(p2_old),
                p2_new=str(p2_new),
            ),
            color=color,
        )

        self.add_field(name="", value="\u3164", inline=False)

        result_display = _get_result_display(result, data, locale)
        self.add_field(
            name=t("shared.field_name.result", locale),
            value=result_display,
            inline=True,
        )

        mmr_text = t(
            "admin_resolution_embed.field_value.mmr_changes",
            locale,
            p1_name=p1_name,
            p1_change=f"{p1_change:+d}",
            p1_old=str(p1_old),
            p1_new=str(p1_new),
            p2_name=p2_name,
            p2_change=f"{p2_change:+d}",
            p2_old=str(p2_old),
            p2_new=str(p2_new),
        )
        self.add_field(
            name=t("shared.field_name.mmr_changes", locale), value=mmr_text, inline=True
        )

        intervention_text = t(
            "admin_resolution_embed.resolved_by.1", locale, admin_name=admin_name
        )
        if reason:
            intervention_text += t(
                "admin_resolution_embed.reason.1", locale, reason=reason
            )
        self.add_field(
            name=t("admin_resolution_embed.field_name.1", locale),
            value=intervention_text,
            inline=False,
        )

        apply_default_embed_footer(self, locale=locale)


class AdminResolution2v2Embed(discord.Embed):
    """Admin confirmation embed for 2v2 admin-resolved matches.

    Mirrors the MatchFinalizedEmbed2v2 layout (rank emotes, flags, race,
    MMR delta) and appends an Admin Intervention field. Green for the
    admin's own view; not used for player DMs (those get MatchFinalizedEmbed2v2).
    """

    def __init__(
        self,
        data: dict,
        *,
        reason: str | None,
        admin_name: str,
        player_infos: dict[int, dict[str, Any] | None] | None = None,
        is_admin_confirm: bool = False,
        locale: str = "enUS",
    ) -> None:
        # Support both "id" (alias added by endpoint) and the raw "match_id".
        match_id = data.get("id", data.get("match_id", "?"))
        # Support both "match_result" (alias) and the raw "result".
        result = data.get("match_result", data.get("result", "?"))
        t1_mmr = data.get("team_1_mmr", 0)
        t2_mmr = data.get("team_2_mmr", 0)
        t1_change = data.get("team_1_mmr_change") or 0
        t2_change = data.get("team_2_mmr_change") or 0
        t1_new = t1_mmr + t1_change
        t2_new = t2_mmr + t2_change

        t1_hdr = _team_header_2v2(
            data, "team_1", player_infos, new_mmr=t1_new, locale=locale
        )
        t2_hdr = _team_header_2v2(
            data, "team_2", player_infos, new_mmr=t2_new, locale=locale
        )

        color = discord.Color.green() if is_admin_confirm else discord.Color.gold()
        title_key = (
            "admin_resolution_embed_2v2.title_confirm.1"
            if is_admin_confirm
            else "admin_resolution_embed_2v2.title_player.1"
        )

        super().__init__(
            title=t(title_key, locale, match_id=str(match_id)),
            description=f"{t1_hdr}\nvs\n{t2_hdr}",
            color=color,
        )

        # Result field — mirrors MatchFinalizedEmbed2v2 exactly.
        if result == "draw":
            result_value = t("shared.result_draw", locale)
        elif result == "invalidated":
            result_value = _result_display_2v2(result, locale)
        elif result == "team_1_win":
            t1_hdr_short = _team_header_2v2(
                data, "team_1", player_infos, show_mmr=False, locale=locale
            )
            result_value = f"🏆 {t1_hdr_short}"
        else:  # team_2_win
            t2_hdr_short = _team_header_2v2(
                data, "team_2", player_infos, show_mmr=False, locale=locale
            )
            result_value = f"🏆 {t2_hdr_short}"

        t1_sign = "+" if t1_change >= 0 else ""
        t2_sign = "+" if t2_change >= 0 else ""

        self.add_field(
            name=t("shared.field_name.result", locale),
            value=result_value,
            inline=True,
        )
        self.add_field(
            name=t("shared.field_name.mmr_changes", locale),
            value=(
                f"- Team 1: `{t1_sign}{t1_change} ({t1_mmr} → {t1_new})`\n"
                f"- Team 2: `{t2_sign}{t2_change} ({t2_mmr} → {t2_new})`"
            ),
            inline=True,
        )

        intervention_text = t(
            "admin_resolution_embed.resolved_by.1", locale, admin_name=admin_name
        )
        if reason:
            intervention_text += t(
                "admin_resolution_embed.reason.1", locale, reason=reason
            )
        self.add_field(
            name=t("admin_resolution_embed.field_name.1", locale),
            value=intervention_text,
            inline=False,
        )

        apply_default_embed_footer(self, locale=locale)


# =========================================================================
# Admin: Status Reset
# =========================================================================


class StatusResetPreviewEmbed(discord.Embed):
    def __init__(
        self, target_discord_uid: int, target_player_name: str, locale: str = "enUS"
    ) -> None:
        super().__init__(
            title=t("status_reset_preview_embed.title.1", locale),
            description=t(
                "status_reset_preview_embed.description.1",
                locale,
                mention=f"<@{target_discord_uid}>",
                username=target_player_name,
                uid=str(target_discord_uid),
            ),
            color=discord.Color.orange(),
        )

        apply_default_embed_footer(self, locale=locale)


class StatusResetSuccessEmbed(discord.Embed):
    def __init__(
        self,
        target_discord_uid: int,
        target_player_name: str,
        old_status: str | None,
        admin: discord.User | discord.Member,
        locale: str = "enUS",
    ) -> None:
        super().__init__(
            title=t("status_reset_success_embed.title.1", locale),
            description=t(
                "status_reset_success_embed.description.1",
                locale,
                mention=f"<@{target_discord_uid}>",
                username=target_player_name,
                uid=str(target_discord_uid),
                old_status=(
                    t(f"player_status.{old_status}", locale)
                    if old_status
                    else t("shared.unknown", locale)
                ),
            ),
            color=discord.Color.green(),
        )
        self.add_field(
            name=t("status_reset_success_embed.field_name.1", locale),
            value=admin.name,
            inline=True,
        )

        apply_default_embed_footer(self, locale=locale)


# =========================================================================
# Owner: Admin
# =========================================================================


class ToggleAdminPreviewEmbed(discord.Embed):
    def __init__(
        self, target_discord_uid: int, target_player_name: str, locale: str = "enUS"
    ) -> None:
        super().__init__(
            title=t("toggle_admin_preview_embed.title.1", locale),
            description=t(
                "toggle_admin_preview_embed.description.1",
                locale,
                mention=f"<@{target_discord_uid}>",
                username=target_player_name,
                uid=str(target_discord_uid),
            ),
            color=discord.Color.orange(),
        )

        apply_default_embed_footer(self, locale=locale)


class ToggleAdminSuccessEmbed(discord.Embed):
    def __init__(
        self,
        target_discord_uid: int,
        target_player_name: str,
        action: str,
        new_role: str,
        locale: str = "enUS",
    ) -> None:
        if action == "promoted":
            title_key = "toggle_admin_success_embed.title_promoted.1"
            color = discord.Color.green()
        elif action == "demoted":
            title_key = "toggle_admin_success_embed.title_demoted.1"
            color = discord.Color.orange()
        else:
            title_key = "toggle_admin_success_embed.title_other.1"
            color = discord.Color.green()

        super().__init__(
            title=t(title_key, locale),
            description=t(
                "toggle_admin_success_embed.description.1",
                locale,
                mention=f"<@{target_discord_uid}>",
                username=target_player_name,
                uid=str(target_discord_uid),
                action=t(f"toggle_admin_success_embed.action.{action}", locale),
                new_role=new_role,
            ),
            color=color,
        )

        apply_default_embed_footer(self, locale=locale)


# =========================================================================
# Owner: MMR
# =========================================================================


class SetMMRPreviewEmbed(discord.Embed):
    def __init__(
        self,
        target_discord_uid: int,
        target_player_name: str,
        race: str,
        new_mmr: int,
        locale: str = "enUS",
    ) -> None:
        try:
            race_emote = get_race_emote(race)
        except ValueError:
            race_emote = "🎮"

        super().__init__(
            title=t("set_mmr_preview_embed.title.1", locale),
            description=t(
                "set_mmr_preview_embed.description.1",
                locale,
                mention=f"<@{target_discord_uid}>",
                username=target_player_name,
                uid=str(target_discord_uid),
                race_emote=str(race_emote),
                race=_race_display(race, locale),
                new_mmr=str(new_mmr),
            ),
            color=discord.Color.orange(),
        )

        apply_default_embed_footer(self, locale=locale)


class SetMMRSuccessEmbed(discord.Embed):
    def __init__(
        self,
        target_discord_uid: int,
        target_player_name: str,
        race: str,
        old_mmr: int | None,
        new_mmr: int,
        locale: str = "enUS",
    ) -> None:
        try:
            race_emote = get_race_emote(race)
        except ValueError:
            race_emote = "🎮"

        old_str = str(old_mmr) if old_mmr is not None else t("shared.na", locale)

        super().__init__(
            title=t("set_mmr_success_embed.title.1", locale),
            description=t(
                "set_mmr_success_embed.description.1",
                locale,
                mention=f"<@{target_discord_uid}>",
                username=target_player_name,
                uid=str(target_discord_uid),
                race_emote=str(race_emote),
                race=_race_display(race, locale),
                old_mmr=old_str,
                new_mmr=str(new_mmr),
            ),
            color=discord.Color.green(),
        )

        apply_default_embed_footer(self, locale=locale)


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
        locale: str = "enUS",
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
            winner_text = t(
                "replay_success_embed.winner_p1.1",
                locale,
                race_emote=p1_race_emote,
                name=p1_name,
            )
        elif winner_result == 2:
            winner_text = t(
                "replay_success_embed.winner_p2.1",
                locale,
                race_emote=p2_race_emote,
                name=p2_name,
            )
        else:
            winner_text = t("replay_success_embed.winner_draw.1", locale)

        minutes, seconds = divmod(duration_seconds, 60)
        duration_text = f"{minutes:02d}:{seconds:02d}"

        observers_text = (
            t(
                "replay_success_embed.observers_detected.1",
                locale,
                names=", ".join(observers),
            )
            if observers
            else t("replay_success_embed.observers_ok.1", locale)
        )

        map_display = map_name.replace(" (", "\n(", 1) if "(" in map_name else map_name

        super().__init__(
            title=t("replay_success_embed.title.1", locale),
            description=t("replay_success_embed.description.1", locale),
            color=discord.Color.light_grey(),
        )

        self.add_field(name="", value="\u3164", inline=False)

        self.add_field(
            name=t("shared.field_name.matchup", locale),
            value=f"**{p1_race_emote} {p1_name}** vs\n**{p2_race_emote} {p2_name}**",
            inline=True,
        )
        self.add_field(
            name=t("shared.field_name.result_header", locale),
            value=winner_text,
            inline=True,
        )
        self.add_field(
            name=t("shared.field_name.map", locale), value=map_display, inline=True
        )

        replay_date_raw = replay_data.get("replay_time") or replay_data.get(
            "replay_date", ""
        )
        start_display = to_display(raw=replay_date_raw)
        if start_display != "—":
            self.add_field(
                name=t("shared.field_name.game_start_time", locale),
                value=start_display,
                inline=True,
            )

        self.add_field(
            name=t("shared.field_name.game_duration", locale),
            value=duration_text,
            inline=True,
        )
        self.add_field(
            name=t("shared.field_name.observers", locale),
            value=observers_text,
            inline=True,
        )

        self.add_field(name="", value="\u3164", inline=False)

        if verification_results:
            verification_text = format_verification(
                verification_results,
                enforcement_enabled=enforcement_enabled,
                auto_resolved=auto_resolved,
            )
            self.add_field(
                name=t("shared.field_name.replay_verification", locale),
                value=verification_text,
                inline=False,
            )

        apply_default_embed_footer(self, locale=locale)


class ReplaySuccessEmbed2v2(discord.Embed):
    """Full replay details embed shown after a successful 2v2 replay parse."""

    def __init__(
        self,
        replay_data: dict[str, Any],
        verification_results: dict[str, Any] | None = None,
        enforcement_enabled: bool = True,
        auto_resolved: bool = False,
        locale: str = "enUS",
    ) -> None:
        t1p1_name: str = replay_data.get("team_1_player_1_name", "Player 1")
        t1p2_name: str = replay_data.get("team_1_player_2_name", "Player 2")
        t2p1_name: str = replay_data.get("team_2_player_1_name", "Player 3")
        t2p2_name: str = replay_data.get("team_2_player_2_name", "Player 4")
        t1p1_race: str = replay_data.get("team_1_player_1_race", "")
        t1p2_race: str = replay_data.get("team_1_player_2_race", "")
        t2p1_race: str = replay_data.get("team_2_player_1_race", "")
        t2p2_race: str = replay_data.get("team_2_player_2_race", "")
        winner_result: int = replay_data.get("result_int", 0)
        map_name: str = replay_data.get("map_name", "Unknown")
        duration_seconds: int = replay_data.get("game_duration_seconds", 0)
        observers: list[str] = replay_data.get("observers", [])

        t1p1_emote = get_race_emote(t1p1_race) if t1p1_race else ""
        t1p2_emote = get_race_emote(t1p2_race) if t1p2_race else ""
        t2p1_emote = get_race_emote(t2p1_race) if t2p1_race else ""
        t2p2_emote = get_race_emote(t2p2_race) if t2p2_race else ""

        team_1_line = f"{t1p1_emote} {t1p1_name} & {t1p2_emote} {t1p2_name}"
        team_2_line = f"{t2p1_emote} {t2p1_name} & {t2p2_emote} {t2p2_name}"

        if winner_result == 1:
            winner_text = t(
                "replay_success_embed_2v2.winner_team_1.1",
                locale,
                team=team_1_line,
            )
        elif winner_result == 2:
            winner_text = t(
                "replay_success_embed_2v2.winner_team_2.1",
                locale,
                team=team_2_line,
            )
        elif winner_result == -1:
            winner_text = t(
                "replay_success_embed_2v2.winner_indeterminate_coerced.1"
                if COERCE_INDETERMINATE_AS_LOSS
                else "replay_success_embed_2v2.winner_indeterminate.1",
                locale,
            )
        else:
            winner_text = t("replay_success_embed.winner_draw.1", locale)

        minutes, seconds = divmod(duration_seconds, 60)
        duration_text = f"{minutes:02d}:{seconds:02d}"

        observers_text = (
            t(
                "replay_success_embed.observers_detected.1",
                locale,
                names=", ".join(observers),
            )
            if observers
            else t("replay_success_embed.observers_ok.1", locale)
        )

        map_display = map_name.replace(" (", "\n(", 1) if "(" in map_name else map_name

        super().__init__(
            title=t("replay_success_embed.title.1", locale),
            description=t("replay_success_embed.description.1", locale),
            color=discord.Color.light_grey(),
        )

        self.add_field(name="", value="\u3164", inline=False)

        self.add_field(
            name=t("shared.field_name.matchup", locale),
            value=f"**{team_1_line}**\nvs\n**{team_2_line}**",
            inline=True,
        )
        self.add_field(
            name=t("shared.field_name.result_header", locale),
            value=winner_text,
            inline=True,
        )
        self.add_field(
            name=t("shared.field_name.map", locale), value=map_display, inline=True
        )

        replay_date_raw = replay_data.get("replay_time") or replay_data.get(
            "replay_date", ""
        )
        start_display = to_display(raw=replay_date_raw)
        if start_display != "—":
            self.add_field(
                name=t("shared.field_name.game_start_time", locale),
                value=start_display,
                inline=True,
            )

        self.add_field(
            name=t("shared.field_name.game_duration", locale),
            value=duration_text,
            inline=True,
        )
        self.add_field(
            name=t("shared.field_name.observers", locale),
            value=observers_text,
            inline=True,
        )

        self.add_field(name="", value="\u3164", inline=False)

        if verification_results:
            verification_text = format_verification(
                verification_results,
                enforcement_enabled=enforcement_enabled,
                auto_resolved=auto_resolved,
            )
            self.add_field(
                name=t("shared.field_name.replay_verification", locale),
                value=verification_text,
                inline=False,
            )

        apply_default_embed_footer(self, locale=locale)


class ReplayErrorEmbed(discord.Embed):
    """Red error embed for a replay parsing failure."""

    def __init__(self, error_message: str, locale: str = "enUS") -> None:
        super().__init__(
            title=t("replay_error_embed.title.1", locale),
            description=t("replay_error_embed.description.1", locale),
            color=discord.Color.red(),
        )
        self.add_field(
            name=t("replay_error_embed.field_name.1", locale),
            value=f"```{error_message[:1000]}```",
            inline=False,
        )

        apply_default_embed_footer(self, locale=locale)


def format_verification(
    results: dict[str, Any],
    enforcement_enabled: bool = True,
    auto_resolved: bool = False,
    locale: str = "enUS",
) -> str:
    lines: list[str] = []

    if "races" in results:
        races_check = results["races"]
        if races_check.get("success"):
            lines.append(t("format_verification.races_match.1", locale))
        else:
            expected = ", ".join(sorted(races_check.get("expected_races", [])))
            played = ", ".join(sorted(races_check.get("played_races", [])))
            lines.append(
                t(
                    "format_verification.races_mismatch.1",
                    locale,
                    expected=expected,
                    played=played,
                )
            )
    else:
        # 2v2: separate check per team
        for team_key in ("races_team_1", "races_team_2"):
            rc = results.get(team_key, {})
            if rc.get("success"):
                lines.append(t("format_verification.races_match.1", locale))
            else:
                expected = ", ".join(sorted(rc.get("expected_races", [])))
                played = ", ".join(sorted(rc.get("played_races", [])))
                lines.append(
                    t(
                        "format_verification.races_mismatch.1",
                        locale,
                        expected=expected,
                        played=played,
                    )
                )

    map_check = results.get("map", {})
    if map_check.get("success"):
        lines.append(t("format_verification.map_match.1", locale))
    else:
        lines.append(
            t(
                "format_verification.map_mismatch.1",
                locale,
                expected_map=str(map_check.get("expected_map")),
                played_map=str(map_check.get("played_map")),
            )
        )

    mod_check = results.get("mod", {})
    if mod_check.get("success"):
        lines.append(
            t(
                "format_verification.mod_valid.1",
                locale,
                message=mod_check.get("message", ""),
            )
        )
    else:
        lines.append(
            t(
                "format_verification.mod_invalid.1",
                locale,
                message=mod_check.get("message", ""),
            )
        )

    ts_check = results.get("timestamp", {})
    if ts_check.get("success"):
        diff = ts_check.get("time_difference_minutes")
        if diff is not None:
            lines.append(
                t(
                    "format_verification.timestamp_valid.1",
                    locale,
                    diff=f"{abs(diff):.1f}",
                )
            )
    else:
        if ts_check.get("error"):
            lines.append(
                t(
                    "format_verification.timestamp_error.1",
                    locale,
                    error=str(ts_check["error"]),
                )
            )
        else:
            diff = ts_check.get("time_difference_minutes")
            if diff is not None:
                if diff < 0:
                    lines.append(
                        t(
                            "format_verification.timestamp_invalid_before.1",
                            locale,
                            diff=f"{abs(diff):.1f}",
                        )
                    )
                else:
                    lines.append(
                        t(
                            "format_verification.timestamp_invalid_after.1",
                            locale,
                            diff=f"{diff:.1f}",
                        )
                    )
            else:
                lines.append(
                    t("format_verification.timestamp_invalid_unknown.1", locale)
                )

    obs_check = results.get("observers", {})
    if obs_check.get("success"):
        lines.append(t("format_verification.observers_ok.1", locale))
    else:
        names = ", ".join(obs_check.get("observers_found", []))
        lines.append(t("format_verification.observers_detected.1", locale, names=names))

    for key, slug in (
        ("game_privacy", "game_privacy"),
        ("game_speed", "game_speed"),
        ("game_duration", "game_duration"),
        ("locked_alliances", "locked_alliances"),
    ):
        chk = results.get(key, {})
        if chk.get("success"):
            lines.append(
                t(
                    f"format_verification.game_setting_ok.{slug}",
                    locale,
                    found=str(chk.get("found")),
                )
            )
        else:
            lines.append(
                t(
                    f"format_verification.game_setting_fail.{slug}",
                    locale,
                    expected=str(chk.get("expected")),
                    found=str(chk.get("found")),
                )
            )

    ai_check = results.get("ai_players", {})
    if ai_check:
        if not ai_check.get("ai_detected", False):
            lines.append(t("format_verification.ai_ok.1", locale))
        elif ai_check.get("success"):
            lines.append(
                t(
                    "format_verification.ai_allowed.1",
                    locale,
                    allow_ai=str(ALLOW_AI_PLAYERS),
                )
            )
        else:
            names = ", ".join(ai_check.get("ai_player_names", []))
            lines.append(
                t(
                    "format_verification.ai_detected.1",
                    locale,
                    allow_ai=str(ALLOW_AI_PLAYERS),
                    names=names,
                )
            )

    is_2v2 = "races" not in results
    race_keys = ("races_team_1", "races_team_2") if is_2v2 else ("races",)
    shared_keys = (
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
    all_ok = all(
        results.get(k, {}).get("success", False) for k in (*race_keys, *shared_keys)
    )
    critical_failed = not all(
        results.get(k, {}).get("success", True) for k in race_keys
    )

    lines.append("")

    if auto_resolved:
        lines.append(t("format_verification.summary_auto_resolved.1", locale))
    elif all_ok:
        lines.append(t("format_verification.summary_all_ok.1", locale))
    elif critical_failed and enforcement_enabled:
        lines.append(t("format_verification.summary_critical_fail.1", locale))
    elif not (enforcement_enabled and critical_failed):
        lines.append(t("format_verification.summary_issues_unlocked.1", locale))
    else:
        lines.append(t("format_verification.summary_issues_locked.1", locale))

    return "\n".join(lines)
