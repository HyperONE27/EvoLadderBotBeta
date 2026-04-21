"""Caster replay search view and results layout.

Triggered by the hidden ``replays`` keyword in DMs (see
:mod:`bot.commands.secret.replay_command`) for players gated by the
``content_creators`` table.

The view holds filter state (game mode, races, map, length bracket, MMR
bracket) and POSTs to ``/caster/replays/search`` when the Search button
is pressed. Results are rendered as a paginated Components v2 layout
(``LayoutView`` + ``Container`` + ``TextDisplay``) in place.
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
from bot.helpers.emotes import get_flag_emote, get_game_emote, get_race_emote
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

_RESULTS_PER_PAGE_1V1 = 10
_RESULTS_PER_PAGE_2V2 = 5
_SEARCH_LIMIT = 500
_TEXT_DISPLAY_CHAR_LIMIT = 4000

_NAME_PAD = 12
_MAP_PAD = 40
_MMR_PAD = 4
_MATCH_ID_PAD = 5


def _fmt_name(name: str) -> str:
    truncated = name[:_NAME_PAD]
    return f"`{truncated:<{_NAME_PAD}}`"


def _fmt_mmr(mmr: int | None) -> str:
    label = str(mmr) if mmr is not None else "—"
    return f"`{label:>{_MMR_PAD}}`"


def _fmt_match_id(match_id: int) -> str:
    return f"`{match_id:>{_MATCH_ID_PAD}}`"


def _fmt_map(map_name: str) -> str:
    truncated = map_name[:_MAP_PAD]
    return f"`{truncated:<{_MAP_PAD}}`"


def _fmt_duration(length_seconds: int) -> str:
    minutes = length_seconds // 60
    seconds = length_seconds % 60
    return f"`{minutes}m{seconds:02d}s`"


def _safe_race_emote(race: str | None) -> str:
    if not race:
        return "  "
    try:
        return get_race_emote(race)
    except ValueError:
        return "  "


def _safe_flag_emote(nationality: str | None) -> str:
    if not nationality:
        return "  "
    try:
        emote = get_flag_emote(nationality)
    except Exception:
        return "  "
    if isinstance(emote, discord.PartialEmoji):
        return str(emote)
    return emote


def _results_per_page(game_mode: str) -> int:
    return _RESULTS_PER_PAGE_1V1 if game_mode == "1v1" else _RESULTS_PER_PAGE_2V2


def _format_row_1v1(result: dict[str, Any], locale: str) -> str:
    players = result.get("players") or []
    races = result.get("races") or []
    nationalities = result.get("nationalities") or []
    side_mmrs = result.get("side_mmrs") or []

    p1 = players[0] if len(players) > 0 else ""
    p2 = players[1] if len(players) > 1 else ""
    r1 = races[0] if len(races) > 0 else None
    r2 = races[1] if len(races) > 1 else None
    n1 = nationalities[0] if len(nationalities) > 0 else None
    n2 = nationalities[1] if len(nationalities) > 1 else None
    m1 = side_mmrs[0] if len(side_mmrs) > 0 else None
    m2 = side_mmrs[1] if len(side_mmrs) > 1 else None

    match_id = int(result.get("match_id") or 0)
    length_seconds = int(result.get("length_seconds") or 0)
    map_name = str(result.get("map_name") or "")
    replay_url = str(result.get("replay_url") or "")

    download_label = t("caster_replay.result.download", locale)
    download = f"[{download_label}]({replay_url})" if replay_url else "—"

    vs_token = t("caster_replay.result.vs", locale)

    line_1 = (
        f"{_fmt_match_id(match_id)} "
        f"{_safe_race_emote(r1)} {_safe_flag_emote(n1)} {_fmt_name(p1)} {_fmt_mmr(m1)} "
        f"{vs_token} "
        f"{_safe_race_emote(r2)} {_safe_flag_emote(n2)} {_fmt_name(p2)} {_fmt_mmr(m2)}"
    )
    line_2 = f"{_fmt_duration(length_seconds)} {_fmt_map(map_name)} {download}"
    return f"{line_1}\n{line_2}"


def _format_row_2v2(result: dict[str, Any], locale: str) -> str:
    players = result.get("players") or []
    races = result.get("races") or []
    nationalities = result.get("nationalities") or []
    side_mmrs = result.get("side_mmrs") or []

    def get(seq: list[Any], idx: int) -> Any:
        return seq[idx] if len(seq) > idx else None

    p = [get(players, i) or "" for i in range(4)]
    r = [get(races, i) for i in range(4)]
    n = [get(nationalities, i) for i in range(4)]
    m1 = get(side_mmrs, 0)
    m2 = get(side_mmrs, 1)

    match_id = int(result.get("match_id") or 0)
    length_seconds = int(result.get("length_seconds") or 0)
    map_name = str(result.get("map_name") or "")
    replay_url = str(result.get("replay_url") or "")

    download_label = t("caster_replay.result.download", locale)
    download = f"[{download_label}]({replay_url})" if replay_url else "—"

    vs_token = t("caster_replay.result.vs", locale)
    vs_cell = f"`{vs_token:>{_MATCH_ID_PAD}}`"

    line_1 = (
        f"{_fmt_match_id(match_id)} "
        f"{_safe_race_emote(r[0])} {_safe_flag_emote(n[0])} {_fmt_name(p[0])} "
        f"{_safe_race_emote(r[1])} {_safe_flag_emote(n[1])} {_fmt_name(p[1])} {_fmt_mmr(m1)}"
    )
    line_2 = (
        f"{vs_cell} "
        f"{_safe_race_emote(r[2])} {_safe_flag_emote(n[2])} {_fmt_name(p[2])} "
        f"{_safe_race_emote(r[3])} {_safe_flag_emote(n[3])} {_fmt_name(p[3])} {_fmt_mmr(m2)}"
    )
    line_3 = f"{_fmt_duration(length_seconds)} {_fmt_map(map_name)} {download}"
    return f"{line_1}\n{line_2}\n{line_3}"


def _build_text_display_content(
    results: list[dict[str, Any]],
    *,
    game_mode: str,
    page: int,
    total_pages: int,
    locale: str,
) -> str:
    total = len(results)
    title = t("caster_replay.results.title", locale, total=str(total))

    if total == 0:
        body = t("caster_replay.results.empty", locale)
        footer = t("embed_brand.footer.1", locale)
        return f"### {title}\n\n{body}\n\n-# {footer}"

    per_page = _results_per_page(game_mode)
    start = page * per_page
    end = min(start + per_page, total)

    header = t(
        "caster_replay.results.page_header",
        locale,
        page=str(page + 1),
        total=str(total_pages),
    )

    formatter = _format_row_1v1 if game_mode == "1v1" else _format_row_2v2
    rows = [formatter(result, locale) for result in results[start:end]]

    footer = t("embed_brand.footer.1", locale)

    content = f"### {title}\n{header}\n\n" + "\n\n".join(rows) + f"\n\n-# {footer}"

    if len(content) > _TEXT_DISPLAY_CHAR_LIMIT:
        logger.warning(
            "[caster] replay page exceeded TextDisplay limit; truncating",
            game_mode=game_mode,
            page=page,
            rendered_length=len(content),
            limit=_TEXT_DISPLAY_CHAR_LIMIT,
        )
        while len(content) > _TEXT_DISPLAY_CHAR_LIMIT and rows:
            rows.pop()
            content = (
                f"### {title}\n{header}\n\n" + "\n\n".join(rows) + f"\n\n-# {footer}"
            )

    return content


class CasterReplayResultsView(discord.ui.LayoutView):
    """Paginated Components v2 layout for replay search results."""

    def __init__(
        self,
        results: list[dict[str, Any]],
        *,
        game_mode: str,
        locale: str = "enUS",
    ) -> None:
        super().__init__(timeout=600)
        self._results = results
        self._game_mode = game_mode
        self._locale = locale
        self._page = 0
        per_page = _results_per_page(game_mode)
        self._total_pages = max(1, (len(results) + per_page - 1) // per_page)
        self.message: discord.Message | None = None
        self._build()

    def _build(self) -> None:
        self.clear_items()
        container: discord.ui.Container[CasterReplayResultsView] = discord.ui.Container(
            accent_colour=discord.Color.green(),
        )
        container.add_item(
            discord.ui.TextDisplay(
                _build_text_display_content(
                    self._results,
                    game_mode=self._game_mode,
                    page=self._page,
                    total_pages=self._total_pages,
                    locale=self._locale,
                )
            )
        )
        self.add_item(container)

        if self._total_pages > 1:
            prev_btn: discord.ui.Button[CasterReplayResultsView] = discord.ui.Button(
                label=t("button.previous", self._locale),
                emoji="◀️",
                style=discord.ButtonStyle.secondary,
                disabled=self._page == 0,
            )
            prev_btn.callback = self._on_prev  # type: ignore[method-assign]

            next_btn: discord.ui.Button[CasterReplayResultsView] = discord.ui.Button(
                label=t("button.next", self._locale),
                emoji="▶️",
                style=discord.ButtonStyle.secondary,
                disabled=self._page >= self._total_pages - 1,
            )
            next_btn.callback = self._on_next  # type: ignore[method-assign]

            action_row: discord.ui.ActionRow[CasterReplayResultsView] = (
                discord.ui.ActionRow(prev_btn, next_btn)
            )
            self.add_item(action_row)

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        if self._page > 0:
            self._page -= 1
        self._build()
        await interaction.response.edit_message(view=self)

    async def _on_next(self, interaction: discord.Interaction) -> None:
        if self._page < self._total_pages - 1:
            self._page += 1
        self._build()
        await interaction.response.edit_message(view=self)


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

            await interaction.response.defer(thinking=True)
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
                        await self._send_error_followup(interaction)
                        return
                    data = await resp.json()

                results = data.get("results") or []
                logger.info(
                    "[caster] replay search ok",
                    game_mode=self.game_mode,
                    count=len(results),
                )
                results_view = CasterReplayResultsView(
                    results, game_mode=self.game_mode, locale=self._locale
                )
                sent = await interaction.followup.send(view=results_view, wait=True)
                results_view.message = sent
            except Exception:
                logger.exception("[caster] replay search failed")
                await self._send_error_followup(interaction)

    async def _send_error_followup(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    title=t("error_embed.title.generic", self._locale),
                    description=t("caster_replay.error.search_failed", self._locale),
                    locale=self._locale,
                )
            )
        except Exception:
            logger.exception("[caster] failed to send error followup")
