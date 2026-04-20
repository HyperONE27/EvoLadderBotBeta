"""Caster replay search view and results embed.

Triggered by the hidden ``replays`` keyword in DMs (see
:mod:`bot.commands.secret.replay_command`) for players gated by the
``content_creators`` table.

The view holds filter state (game mode, races, map, length bracket, MMR
bracket) and POSTs to ``/caster/replays/search`` when the Search button
is pressed. Results are rendered as a paginated embed in place.
"""

from __future__ import annotations

import asyncio
from typing import Any

import discord
import structlog

from bot.components.embeds import ErrorEmbed
from bot.components.views import AutoDisableView
from bot.core.config import BACKEND_URL, CURRENT_SEASON
from bot.core.http import get_session
from bot.helpers.embed_branding import apply_default_embed_footer
from bot.helpers.emotes import get_game_emote, get_race_emote
from common.datetime_helpers import ensure_utc, to_discord_timestamp
from common.i18n import t
from common.lookups.map_lookups import get_maps
from common.lookups.race_lookups import get_races

logger = structlog.get_logger(__name__)

_GAME_MODES = ("1v1", "2v2")

# Length bracket keys map to (min_minutes, max_minutes) or None for "any".
_LENGTH_BRACKETS: dict[str, tuple[int | None, int | None]] = {
    "any": (None, None),
    "under_10": (None, 10),
    "10_to_20": (10, 20),
    "20_to_30": (20, 30),
    "over_30": (30, None),
}

_MMR_BRACKETS: dict[str, tuple[int | None, int | None]] = {
    "any": (None, None),
    "under_1000": (None, 1000),
    "1000_to_1500": (1000, 1500),
    "1500_to_2000": (1500, 2000),
    "over_2000": (2000, None),
}

_RESULTS_PER_PAGE = 5
_SEARCH_LIMIT = 50


class CasterReplayResultsEmbed(discord.Embed):
    """Paginated embed rendering replay search results."""

    def __init__(
        self,
        results: list[dict[str, Any]],
        *,
        page: int,
        total_pages: int,
        locale: str = "enUS",
    ) -> None:
        total = len(results)
        title = t("caster_replay.results.title", locale, total=str(total))
        if total == 0:
            super().__init__(
                title=title,
                description=t("caster_replay.results.empty", locale),
                color=discord.Color.orange(),
            )
            apply_default_embed_footer(self, locale=locale)
            return

        start = page * _RESULTS_PER_PAGE
        end = min(start + _RESULTS_PER_PAGE, total)
        description_lines: list[str] = [
            t(
                "caster_replay.results.page_header",
                locale,
                page=str(page + 1),
                total=str(total_pages),
            )
        ]
        super().__init__(
            title=title,
            description="\n".join(description_lines),
            color=discord.Color.green(),
        )

        for result in results[start:end]:
            field_name = t(
                "caster_replay.result.match_header",
                locale,
                match_id=str(result.get("match_id", "?")),
                game_mode=result.get("game_mode", ""),
            )

            players = result.get("players") or []
            races = result.get("races") or []
            race_pairs: list[str] = []
            for idx, player in enumerate(players):
                race = races[idx] if idx < len(races) else None
                emote = get_race_emote(race) if race else ""
                race_pairs.append(f"{emote} {player}".strip())
            players_line = " vs ".join(race_pairs) if race_pairs else "—"

            length_seconds = int(result.get("length_seconds") or 0)
            length_label = (
                f"{length_seconds // 60}:{length_seconds % 60:02d}"
                if length_seconds
                else "—"
            )
            map_name = result.get("map_name") or "—"
            mmr_avg = result.get("mmr_avg")
            mmr_label = str(mmr_avg) if mmr_avg is not None else "—"

            played_at = ensure_utc(result.get("played_at"))
            played_label = (
                to_discord_timestamp(dt=played_at, style="R") if played_at else "—"
            )

            replay_url = result.get("replay_url") or ""
            download_line = (
                f"[{t('caster_replay.result.download', locale)}]({replay_url})"
                if replay_url
                else "—"
            )

            field_value = (
                f"{players_line}\n"
                + t(
                    "caster_replay.result.details",
                    locale,
                    map_name=map_name,
                    length=length_label,
                    mmr=mmr_label,
                    played_at=played_label,
                )
                + f"\n{download_line}"
            )
            self.add_field(name=field_name, value=field_value, inline=False)

        apply_default_embed_footer(self, locale=locale)


class CasterReplayResultsView(AutoDisableView):
    """Pagination controls for replay search results."""

    def __init__(
        self,
        results: list[dict[str, Any]],
        *,
        locale: str = "enUS",
    ) -> None:
        super().__init__(timeout=600)
        self._results = results
        self._locale = locale
        self._page = 0
        self._total_pages = max(
            1, (len(results) + _RESULTS_PER_PAGE - 1) // _RESULTS_PER_PAGE
        )
        self._build()

    def _build(self) -> None:
        self.clear_items()
        prev_btn: discord.ui.Button[CasterReplayResultsView] = discord.ui.Button(
            label=t("button.previous", self._locale),
            emoji="◀️",
            style=discord.ButtonStyle.secondary,
            disabled=self._page == 0,
            row=0,
        )
        prev_btn.callback = self._on_prev  # type: ignore[method-assign]
        self.add_item(prev_btn)

        next_btn: discord.ui.Button[CasterReplayResultsView] = discord.ui.Button(
            label=t("button.next", self._locale),
            emoji="▶️",
            style=discord.ButtonStyle.secondary,
            disabled=self._page >= self._total_pages - 1,
            row=0,
        )
        next_btn.callback = self._on_next  # type: ignore[method-assign]
        self.add_item(next_btn)

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        if self._page > 0:
            self._page -= 1
        self._build()
        await interaction.response.edit_message(
            embed=CasterReplayResultsEmbed(
                self._results,
                page=self._page,
                total_pages=self._total_pages,
                locale=self._locale,
            ),
            view=self,
        )

    async def _on_next(self, interaction: discord.Interaction) -> None:
        if self._page < self._total_pages - 1:
            self._page += 1
        self._build()
        await interaction.response.edit_message(
            embed=CasterReplayResultsEmbed(
                self._results,
                page=self._page,
                total_pages=self._total_pages,
                locale=self._locale,
            ),
            view=self,
        )


class _GameModeSelect(discord.ui.Select["CasterReplaySearchView"]):
    def __init__(self, selected: str, locale: str) -> None:
        options = [
            discord.SelectOption(
                label=t(f"caster_replay.game_mode.{mode}", locale),
                value=mode,
                default=(mode == selected),
            )
            for mode in _GAME_MODES
        ]
        super().__init__(
            placeholder=t("caster_replay.placeholder.game_mode", locale),
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        view.game_mode = self.values[0]
        view.map_name = None
        view._rebuild()
        await interaction.response.edit_message(view=view)


class _RaceFilterSelect(discord.ui.Select["CasterReplaySearchView"]):
    def __init__(self, selected: list[str], locale: str) -> None:
        races = get_races()
        options = [
            discord.SelectOption(
                label=t(f"race.{code}.name", locale),
                value=code,
                emoji=get_race_emote(code),
                default=(code in selected),
            )
            for code in races
        ]
        super().__init__(
            placeholder=t("caster_replay.placeholder.races", locale),
            min_values=0,
            max_values=min(2, len(options)),
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        view.races = list(self.values)
        await interaction.response.defer()


class _MapFilterSelect(discord.ui.Select["CasterReplaySearchView"]):
    def __init__(self, game_mode: str, selected: str | None, locale: str) -> None:
        maps = get_maps(game_mode=game_mode, season=CURRENT_SEASON) or {}
        options = [
            discord.SelectOption(
                label=map_data["short_name"],
                value=map_name,
                emoji=get_game_emote(map_data.get("game", "sc2")),
                default=(map_name == selected),
            )
            for map_name, map_data in sorted(maps.items())
        ]
        if not options:
            options = [
                discord.SelectOption(
                    label=t("caster_replay.map.no_maps", locale), value="none"
                )
            ]
        super().__init__(
            placeholder=t("caster_replay.placeholder.map", locale),
            min_values=0,
            max_values=1,
            options=options,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        value = self.values[0] if self.values else None
        view.map_name = value if value and value != "none" else None
        await interaction.response.defer()


class _LengthBracketSelect(discord.ui.Select["CasterReplaySearchView"]):
    def __init__(self, selected: str, locale: str) -> None:
        options = [
            discord.SelectOption(
                label=t(f"caster_replay.length.{key}", locale),
                value=key,
                default=(key == selected),
            )
            for key in _LENGTH_BRACKETS
        ]
        super().__init__(
            placeholder=t("caster_replay.placeholder.length", locale),
            min_values=1,
            max_values=1,
            options=options,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        view.length_bracket = self.values[0]
        await interaction.response.defer()


class CasterReplaySearchView(AutoDisableView):
    """Filter view for caster replay search (DM-only, content-creator gated)."""

    def __init__(
        self,
        *,
        caster_discord_uid: int,
        locale: str = "enUS",
    ) -> None:
        super().__init__(timeout=900)
        self._caster_discord_uid = caster_discord_uid
        self._locale = locale
        self.game_mode: str = "1v1"
        self.races: list[str] = []
        self.map_name: str | None = None
        self.length_bracket: str = "any"
        self._search_lock = asyncio.Lock()
        self._rebuild()

    def _rebuild(self) -> None:
        self.clear_items()
        self.add_item(_GameModeSelect(self.game_mode, self._locale))
        self.add_item(_RaceFilterSelect(self.races, self._locale))
        self.add_item(_MapFilterSelect(self.game_mode, self.map_name, self._locale))
        self.add_item(_LengthBracketSelect(self.length_bracket, self._locale))

        search_btn: discord.ui.Button[CasterReplaySearchView] = discord.ui.Button(
            label=t("caster_replay.button.search", self._locale),
            emoji="🔍",
            style=discord.ButtonStyle.primary,
            row=4,
        )
        search_btn.callback = self._on_search  # type: ignore[method-assign]
        self.add_item(search_btn)

    async def _on_search(self, interaction: discord.Interaction) -> None:
        if self._search_lock.locked():
            await interaction.response.defer()
            return
        async with self._search_lock:
            min_len, max_len = _LENGTH_BRACKETS[self.length_bracket]
            payload: dict[str, Any] = {
                "caster_discord_uid": self._caster_discord_uid,
                "game_mode": self.game_mode,
                "races": self.races,
                "limit": _SEARCH_LIMIT,
            }
            if self.map_name:
                payload["map_name"] = self.map_name
            if min_len is not None:
                payload["min_length_minutes"] = min_len
            if max_len is not None:
                payload["max_length_minutes"] = max_len

            await interaction.response.defer()
            try:
                async with get_session().post(
                    f"{BACKEND_URL}/caster/replays/search",
                    json=payload,
                ) as resp:
                    if resp.status >= 400:
                        detail = "unknown"
                        try:
                            data = await resp.json()
                            detail = data.get("detail") or detail
                        except Exception:
                            pass
                        logger.warning(
                            "[caster] replay search failed",
                            status=resp.status,
                            detail=detail,
                        )
                        await interaction.followup.send(
                            embed=ErrorEmbed(
                                title=t("error_embed.title.generic", self._locale),
                                description=t(
                                    "caster_replay.error.search_failed", self._locale
                                ),
                                locale=self._locale,
                            )
                        )
                        return
                    data = await resp.json()
            except Exception:
                logger.exception("[caster] replay search request raised")
                await interaction.followup.send(
                    embed=ErrorEmbed(
                        title=t("error_embed.title.generic", self._locale),
                        description=t(
                            "caster_replay.error.search_failed", self._locale
                        ),
                        locale=self._locale,
                    )
                )
                return

            results = data.get("results") or []
            total_pages = max(
                1, (len(results) + _RESULTS_PER_PAGE - 1) // _RESULTS_PER_PAGE
            )
            results_view = CasterReplayResultsView(results, locale=self._locale)
            results_view.message = await interaction.followup.send(  # type: ignore[func-returns-value]
                embed=CasterReplayResultsEmbed(
                    results,
                    page=0,
                    total_pages=total_pages,
                    locale=self._locale,
                ),
                view=results_view,
            )
