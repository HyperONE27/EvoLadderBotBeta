"""Caster replay search view and results layout.

Triggered by the hidden ``replays`` keyword in DMs (see
:mod:`bot.commands.secret.replay_command`) for players gated by the
``content_creators`` table.

A single ``LayoutView`` holds both the filter controls (game mode,
races, map, min length, max length) and the paginated results rendered
in a ``Container`` + ``TextDisplay``. Every interaction edits the same
message so dropdown adjustments and repeated searches don't flood the
channel.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import discord
import structlog

from bot.core.config import BACKEND_URL
from bot.core.http import get_session
from bot.helpers.emotes import get_flag_emote, get_game_emote, get_race_emote
from common.datetime_helpers import ensure_utc
from common.i18n import t
from common.lookups.map_lookups import get_maps
from common.lookups.race_lookups import get_races

logger = structlog.get_logger(__name__)

_GAME_MODES = ("1v1", "2v2")
_GAME_MODE_EMOJIS = {"1v1": "👤", "2v2": "👥"}

_MIN_LENGTH_OPTIONS = list(range(1, 26))  # 1, 2, ..., 25 minutes
_MAX_LENGTH_OPTIONS = list(range(2, 51, 2))  # 2, 4, ..., 50 minutes

_RESULTS_PER_PAGE_1V1 = 10
_RESULTS_PER_PAGE_2V2 = 5
_SEARCH_LIMIT = 500
_TEXT_DISPLAY_CHAR_LIMIT = 4000

_NAME_PAD = 12
_MMR_PAD = 4
_MATCH_ID_PAD = 7
_DURATION_PAD = 7


def _fmt_name(name: str) -> str:
    truncated = name[:_NAME_PAD]
    return f"`{truncated:<{_NAME_PAD}}`"


def _fmt_mmr(mmr: int | None) -> str:
    label = str(mmr) if mmr is not None else "—"
    return f"`{label:>{_MMR_PAD}}`"


def _fmt_match_id(match_id: int) -> str:
    return f"`{match_id:>{_MATCH_ID_PAD}}`"


def _fmt_duration(length_seconds: int) -> str:
    minutes = length_seconds // 60
    seconds = length_seconds % 60
    raw = f"{minutes}m{seconds:02d}s"
    return f"`{raw:>{_DURATION_PAD}}`"


def _fmt_played_at(raw: Any) -> str:
    dt = ensure_utc(raw)
    label = dt.strftime("%Y-%m-%d") if dt else "—"
    return f"`{label}`"


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
    played_at = result.get("played_at")

    download_label = t("caster_replay.result.download", locale)
    download = f"[{download_label}]({replay_url})" if replay_url else "—"

    vs_token = t("caster_replay.result.vs", locale)

    line_1 = (
        f"{_fmt_match_id(match_id)} "
        f"{_safe_race_emote(r1)} {_safe_flag_emote(n1)} {_fmt_name(p1)} {_fmt_mmr(m1)} "
        f"{vs_token} "
        f"{_safe_race_emote(r2)} {_safe_flag_emote(n2)} {_fmt_name(p2)} {_fmt_mmr(m2)}"
    )
    line_2 = f"{_fmt_duration(length_seconds)} {_fmt_played_at(played_at)} `{map_name}`"
    return f"{line_1}\n{line_2}\n{download}"


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
    played_at = result.get("played_at")

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
    line_3 = f"{_fmt_duration(length_seconds)} {_fmt_played_at(played_at)} `{map_name}`"
    return f"{line_1}\n{line_2}\n{line_3}\n{download}"


def _build_results_content(
    results: list[dict[str, Any]],
    *,
    game_mode: str,
    page: int,
    total_pages: int,
    locale: str,
) -> str:
    total = len(results)
    title = t("caster_replay.results.title", locale, total=str(total))
    footer = t("embed_brand.footer.1", locale)

    if total == 0:
        body = t("caster_replay.results.empty", locale)
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


def _build_prompt_content(locale: str) -> str:
    title = t("caster_replay.results.title_initial", locale)
    prompt = t("caster_replay.results.prompt", locale)
    footer = t("embed_brand.footer.1", locale)
    return f"### {title}\n\n{prompt}\n\n-# {footer}"


def _build_error_content(locale: str) -> str:
    title = t("caster_replay.results.title_initial", locale)
    body = t("caster_replay.error.search_failed", locale)
    footer = t("embed_brand.footer.1", locale)
    return f"### {title}\n\n{body}\n\n-# {footer}"


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
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        view.races = list(self.values)
        await interaction.response.defer()


class _MapFilterSelect(discord.ui.Select["CasterReplaySearchView"]):
    def __init__(self, game_mode: str, selected: str | None, locale: str) -> None:
        maps = get_maps(game_mode=game_mode) or {}
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
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        value = self.values[0] if self.values else None
        view.map_name = value if value and value != "none" else None
        await interaction.response.defer()


class _MinLengthSelect(discord.ui.Select["CasterReplaySearchView"]):
    def __init__(self, selected: int | None, locale: str) -> None:
        options = [
            discord.SelectOption(
                label=t("caster_replay.length.minutes", locale, minutes=str(n)),
                value=str(n),
                default=(n == selected),
            )
            for n in _MIN_LENGTH_OPTIONS
        ]
        super().__init__(
            placeholder=t("caster_replay.placeholder.length_min", locale),
            min_values=0,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        view.min_length_minutes = int(self.values[0]) if self.values else None
        await interaction.response.defer()


class _MaxLengthSelect(discord.ui.Select["CasterReplaySearchView"]):
    def __init__(self, selected: int | None, locale: str) -> None:
        options = [
            discord.SelectOption(
                label=t("caster_replay.length.minutes", locale, minutes=str(n)),
                value=str(n),
                default=(n == selected),
            )
            for n in _MAX_LENGTH_OPTIONS
        ]
        super().__init__(
            placeholder=t("caster_replay.placeholder.length_max", locale),
            min_values=0,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        view.max_length_minutes = int(self.values[0]) if self.values else None
        await interaction.response.defer()


class CasterReplaySearchView(discord.ui.LayoutView):
    """Combined filter controls and results — all in one message, edited in place."""

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
        self.min_length_minutes: int | None = None
        self.max_length_minutes: int | None = None

        self._results: list[dict[str, Any]] = []
        self._has_searched: bool = False
        self._page: int = 0
        self._error: bool = False

        self._search_lock = asyncio.Lock()
        self.message: discord.Message | None = None
        self._rebuild()

    @property
    def _total_pages(self) -> int:
        per_page = _results_per_page(self.game_mode)
        return max(1, (len(self._results) + per_page - 1) // per_page)

    def _rebuild(self) -> None:
        self.clear_items()

        if self._error:
            body = _build_error_content(self._locale)
        elif self._has_searched:
            body = _build_results_content(
                self._results,
                game_mode=self.game_mode,
                page=self._page,
                total_pages=self._total_pages,
                locale=self._locale,
            )
        else:
            body = _build_prompt_content(self._locale)

        container: discord.ui.Container[CasterReplaySearchView] = discord.ui.Container(
            accent_colour=discord.Color.green(),
        )
        container.add_item(discord.ui.TextDisplay(body))
        self.add_item(container)

        if self._has_searched and not self._error and self._total_pages > 1:
            skip_prev_btn: discord.ui.Button[CasterReplaySearchView] = (
                discord.ui.Button(
                    emoji="⏪",
                    style=discord.ButtonStyle.secondary,
                    disabled=self._page == 0,
                )
            )
            skip_prev_btn.callback = self._on_skip_prev  # type: ignore[method-assign]
            prev_btn: discord.ui.Button[CasterReplaySearchView] = discord.ui.Button(
                label=t("button.previous", self._locale),
                emoji="◀️",
                style=discord.ButtonStyle.secondary,
                disabled=self._page == 0,
            )
            prev_btn.callback = self._on_prev  # type: ignore[method-assign]
            next_btn: discord.ui.Button[CasterReplaySearchView] = discord.ui.Button(
                label=t("button.next", self._locale),
                emoji="▶️",
                style=discord.ButtonStyle.secondary,
                disabled=self._page >= self._total_pages - 1,
            )
            next_btn.callback = self._on_next  # type: ignore[method-assign]
            skip_next_btn: discord.ui.Button[CasterReplaySearchView] = (
                discord.ui.Button(
                    emoji="⏩",
                    style=discord.ButtonStyle.secondary,
                    disabled=self._page >= self._total_pages - 1,
                )
            )
            skip_next_btn.callback = self._on_skip_next  # type: ignore[method-assign]
            pagination_row: discord.ui.ActionRow[CasterReplaySearchView] = (
                discord.ui.ActionRow(skip_prev_btn, prev_btn, next_btn, skip_next_btn)
            )
            self.add_item(pagination_row)

        self.add_item(discord.ui.ActionRow(_RaceFilterSelect(self.races, self._locale)))
        self.add_item(
            discord.ui.ActionRow(
                _MapFilterSelect(self.game_mode, self.map_name, self._locale)
            )
        )
        self.add_item(
            discord.ui.ActionRow(
                _MinLengthSelect(self.min_length_minutes, self._locale)
            )
        )
        self.add_item(
            discord.ui.ActionRow(
                _MaxLengthSelect(self.max_length_minutes, self._locale)
            )
        )

        mode_buttons: list[discord.ui.Button[CasterReplaySearchView]] = []
        for mode in _GAME_MODES:
            mode_btn: discord.ui.Button[CasterReplaySearchView] = discord.ui.Button(
                label=t(f"caster_replay.game_mode.{mode}", self._locale),
                emoji=_GAME_MODE_EMOJIS[mode],
                style=(
                    discord.ButtonStyle.primary
                    if self.game_mode == mode
                    else discord.ButtonStyle.secondary
                ),
            )
            mode_btn.callback = self._make_game_mode_callback(mode)  # type: ignore[method-assign,assignment]
            mode_buttons.append(mode_btn)

        search_btn: discord.ui.Button[CasterReplaySearchView] = discord.ui.Button(
            label=t("caster_replay.button.search", self._locale),
            emoji="🔍",
            style=discord.ButtonStyle.primary,
        )
        search_btn.callback = self._on_search  # type: ignore[method-assign]

        controls_row: discord.ui.ActionRow[CasterReplaySearchView] = (
            discord.ui.ActionRow(*mode_buttons, search_btn)
        )
        self.add_item(controls_row)

    def _make_game_mode_callback(
        self, mode: str
    ) -> Callable[[discord.Interaction], Coroutine[Any, Any, None]]:
        async def callback(interaction: discord.Interaction) -> None:
            if self.game_mode == mode:
                await interaction.response.defer()
                return
            self.game_mode = mode
            self.map_name = None
            # Reset page on mode change since per_page may change.
            self._page = 0
            self._rebuild()
            await interaction.response.edit_message(view=self)

        return callback

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        if self._page > 0:
            self._page -= 1
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _on_next(self, interaction: discord.Interaction) -> None:
        if self._page < self._total_pages - 1:
            self._page += 1
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _on_skip_prev(self, interaction: discord.Interaction) -> None:
        self._page = max(0, self._page - 5)
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _on_skip_next(self, interaction: discord.Interaction) -> None:
        self._page = min(self._total_pages - 1, self._page + 5)
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _on_search(self, interaction: discord.Interaction) -> None:
        if self._search_lock.locked():
            await interaction.response.defer()
            return
        async with self._search_lock:
            await interaction.response.defer()
            payload: dict[str, Any] = {
                "caster_discord_uid": self._caster_discord_uid,
                "game_mode": self.game_mode,
                "races": self.races,
                "limit": _SEARCH_LIMIT,
            }
            if self.map_name:
                payload["map_name"] = self.map_name
            if self.min_length_minutes is not None:
                payload["min_length_minutes"] = self.min_length_minutes
            if self.max_length_minutes is not None:
                payload["max_length_minutes"] = self.max_length_minutes

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
                        self._error = True
                        self._rebuild()
                        await interaction.edit_original_response(view=self)
                        return
                    data = await resp.json()

                results = data.get("results") or []
                logger.info(
                    "[caster] replay search ok",
                    game_mode=self.game_mode,
                    count=len(results),
                )
                self._results = results
                self._has_searched = True
                self._error = False
                self._page = 0
                self._rebuild()
                await interaction.edit_original_response(view=self)
            except Exception:
                logger.exception("[caster] replay search failed")
                self._error = True
                self._rebuild()
                try:
                    await interaction.edit_original_response(view=self)
                except Exception:
                    logger.exception("[caster] failed to edit message with error state")

    async def on_timeout(self) -> None:
        for item in self.walk_children():
            if hasattr(item, "disabled"):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass
            except discord.HTTPException:
                logger.warning(
                    "[caster] failed to disable view on timeout", exc_info=True
                )
