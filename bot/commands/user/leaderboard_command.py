import structlog

import discord
from discord import app_commands

from bot.core.config import (
    BACKEND_URL,
    EXCLUDE_INACTIVE_PLAYERS_FROM_LETTER_RANK,
    GAME_MODE_CHOICES,
)
from bot.core.dependencies import get_cache, get_player_locale
from bot.core.http import get_session
from bot.helpers.checks import (
    check_if_accepted_tos,
    check_if_banned,
    check_if_completed_setup,
    check_if_dm,
)
from bot.helpers.emotes import get_flag_emote, get_race_emote, get_rank_emote
from common.i18n import t
from common.lookups.country_lookups import get_common_countries
from common.lookups.race_lookups import get_bw_race_codes, get_races, get_sc2_race_codes

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PAGE_SIZE = 40
_PLAYERS_PER_FIELD = 5

_RANKED_ONLY = "_ranked"  # Sentinel: show all players with a letter rank (not U)
_RANK_CYCLE: list[str | None] = [None, _RANKED_ONLY, "S", "A", "B", "C", "D", "E", "F"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _race_display(race_code: str, locale: str = "enUS") -> str:
    return t(f"race.{race_code}.name", locale)


def _country_display(code: str, locale: str = "enUS") -> str:
    translated = t(f"country.{code}.name", locale)
    return translated if translated != f"country.{code}.name" else code


async def _ensure_leaderboard(caller_uid: int) -> list[dict]:
    """Return the cached leaderboard, fetching from the backend if empty."""
    cache = get_cache()
    if cache.leaderboard_1v1:
        return cache.leaderboard_1v1

    try:
        async with get_session().get(
            f"{BACKEND_URL}/leaderboard_1v1", params={"caller_uid": caller_uid}
        ) as resp:
            data = await resp.json()
        entries: list[dict] = data.get("leaderboard", [])
        cache.leaderboard_1v1 = entries
        return entries
    except Exception:
        logger.exception("Failed to fetch leaderboard from backend")
        return []


def _apply_filters(
    entries: list[dict],
    *,
    race_filter: list[str] | None = None,
    nationality_filter: list[str] | None = None,
    best_race_only: bool = False,
    rank_filter: str | None = None,
) -> list[dict]:
    """Filter the leaderboard entries in-memory."""
    result = entries

    if best_race_only:
        # Keep only the highest-MMR entry per player.
        seen: dict[int, dict] = {}
        for entry in result:
            uid = entry["discord_uid"]
            if uid not in seen or entry["mmr"] > seen[uid]["mmr"]:
                seen[uid] = entry
        result = list(seen.values())

    if race_filter:
        race_set = set(race_filter)
        result = [e for e in result if e["race"] in race_set]

    if nationality_filter:
        nat_set = set(nationality_filter)
        result = [e for e in result if e["nationality"] in nat_set]

    if rank_filter == _RANKED_ONLY:
        result = [e for e in result if e["letter_rank"] != "U"]
    elif rank_filter:
        result = [e for e in result if e["letter_rank"] == rank_filter]

    return result


# ---------------------------------------------------------------------------
# Embeds
# ---------------------------------------------------------------------------


class LeaderboardEmbed(discord.Embed):
    def __init__(
        self,
        entries: list[dict],
        page: int,
        total_pages: int,
        total_players: int,
        *,
        race_filter: list[str] | None = None,
        nationality_filter: list[str] | None = None,
        best_race_only: bool = False,
        rank_filter: str | None = None,
        locale: str = "enUS",
    ) -> None:
        super().__init__(
            title=t("leaderboard_embed.title.1", locale), color=discord.Color.gold()
        )

        # Filter summary — display in canonical order, not click order.
        _race_order = get_bw_race_codes() + get_sc2_race_codes()
        sorted_races = sorted(
            race_filter or [],
            key=lambda r: (
                _race_order.index(r) if r in _race_order else len(_race_order)
            ),
        )
        all_label = t("leaderboard_embed.label_all.1", locale)
        race_label = (
            ", ".join(_race_display(r, locale) for r in sorted_races)
            if sorted_races
            else all_label
        )

        sorted_nats = sorted(
            nationality_filter or [], key=lambda c: _country_display(c, locale)
        )
        nat_label = (
            ", ".join(_country_display(c, locale) for c in sorted_nats)
            if sorted_nats
            else all_label
        )
        if rank_filter is None:
            rank_label = all_label
        elif rank_filter == _RANKED_ONLY:
            rank_label = t("leaderboard_embed.label_ranked_only.1", locale)
        else:
            rank_label = rank_filter
        parts: list[str] = [
            t("leaderboard_embed.filter_race.1", locale, race_label=race_label),
            t("leaderboard_embed.filter_nationality.1", locale, nat_label=nat_label),
            t("leaderboard_embed.filter_rank.1", locale, rank_label=rank_label),
        ]
        if best_race_only:
            parts.append(t("leaderboard_embed.filter_best_race.1", locale))
        self.add_field(name="", value="\n".join(parts), inline=False)

        # Leaderboard rows
        start = (page - 1) * _PAGE_SIZE
        page_entries = entries[start : start + _PAGE_SIZE]

        if not page_entries:
            self.add_field(
                name=t("leaderboard_embed.field_name_empty.1", locale),
                value=t("leaderboard_embed.no_players.1", locale),
                inline=False,
            )
        else:
            chunks: list[str] = []
            for i in range(0, len(page_entries), _PLAYERS_PER_FIELD):
                chunk = page_entries[i : i + _PLAYERS_PER_FIELD]
                lines: list[str] = []
                for entry in chunk:
                    rank_emote = get_rank_emote(entry["letter_rank"])
                    race_emote = get_race_emote(entry["race"])
                    flag_emote = get_flag_emote(entry["nationality"] or "XX")
                    if EXCLUDE_INACTIVE_PLAYERS_FROM_LETTER_RANK:
                        active_rank = entry.get("active_ordinal_rank", -1)
                        ordinal = f"{active_rank:>4d}" if active_rank > 0 else "   -"
                    else:
                        ordinal = f"{entry['ordinal_rank']:>4d}"
                    name = f"{entry['player_name'][:12]:<12}"
                    mmr = entry["mmr"]
                    lines.append(
                        f"`{ordinal}.` {rank_emote} {race_emote} {flag_emote} `{name}` `{mmr}`"
                    )
                chunks.append("\n".join(lines))

            # 2-column grid: pairs of inline fields
            for i in range(0, len(chunks), 2):
                pair_idx = i // 2
                pair_start = start + pair_idx * 10 + 1
                pair_end = pair_start + 9
                self.add_field(
                    name=t(
                        "leaderboard_embed.field_name.1",
                        locale,
                        start=str(pair_start),
                        end=str(pair_end),
                    ),
                    value=chunks[i],
                    inline=True,
                )
                if i + 1 < len(chunks):
                    self.add_field(name="\u200b", value=chunks[i + 1], inline=True)
                if i + 2 < len(chunks):
                    self.add_field(name=" ", value=" ", inline=False)

        self.set_footer(
            text=t(
                "leaderboard_embed.footer.1",
                locale,
                page=str(page),
                total_pages=str(total_pages),
                total_players=str(total_players),
            )
        )


# ---------------------------------------------------------------------------
# Selects
# ---------------------------------------------------------------------------


class RaceFilterSelect(discord.ui.Select["LeaderboardView"]):
    def __init__(self, selected: list[str] | None = None, locale: str = "enUS") -> None:
        selected = selected or []
        options: list[discord.SelectOption] = []
        all_codes = get_bw_race_codes() + get_sc2_race_codes()
        for code in all_codes:
            if get_races().get(code) is None:
                continue
            options.append(
                discord.SelectOption(
                    label=_race_display(code, locale),
                    value=code,
                    emoji=get_race_emote(code),
                    default=code in selected,
                )
            )
        super().__init__(
            placeholder=t("leaderboard.select.race_placeholder", locale),
            min_values=0,
            max_values=len(options),
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.race_filter = self.values or None
        self.view.current_page = 1
        await self.view.refresh(interaction)


def _common_country_options(locale: str = "enUS") -> list[discord.SelectOption]:
    """Return SelectOptions for all common countries, sorted by ISO code."""
    country_list = sorted(get_common_countries().values(), key=lambda c: c["code"])
    return [
        discord.SelectOption(
            label=f"({c['code']}) {_country_display(c['code'], locale)}",
            value=c["code"],
            emoji=get_flag_emote(c["code"]),
        )
        for c in country_list
    ]


class CountryFilterPage1Select(discord.ui.Select["LeaderboardView"]):
    """Nationality filter -- first 25 common countries (sorted by localized name)."""

    def __init__(self, selected: list[str] | None = None, locale: str = "enUS") -> None:
        selected = selected or []
        all_options = _common_country_options(locale)
        options = all_options[:25]
        for opt in options:
            opt.default = opt.value in selected
        super().__init__(
            placeholder=t("leaderboard.select.nationality_page1_placeholder", locale),
            min_values=0,
            max_values=25,
            options=options,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.country_page1_selection = list(self.values)
        self.view.current_page = 1
        await self.view.refresh(interaction)


class CountryFilterPage2Select(discord.ui.Select["LeaderboardView"]):
    """Nationality filter -- next 25 common countries (sorted by localized name)."""

    def __init__(self, selected: list[str] | None = None, locale: str = "enUS") -> None:
        selected = selected or []
        all_options = _common_country_options(locale)
        options = all_options[25:50]
        for opt in options:
            opt.default = opt.value in selected
        super().__init__(
            placeholder=t("leaderboard.select.nationality_page2_placeholder", locale),
            min_values=0,
            max_values=25,
            options=options,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.country_page2_selection = list(self.values)
        self.view.current_page = 1
        await self.view.refresh(interaction)


class PageNavigationSelect(discord.ui.Select["LeaderboardView"]):
    def __init__(
        self, total_pages: int, current_page: int, locale: str = "enUS"
    ) -> None:
        options = [
            discord.SelectOption(
                label=t("leaderboard.select.page_option", locale, page=str(p)),
                value=str(p),
                default=p == current_page,
            )
            for p in range(1, total_pages + 1)
        ]
        super().__init__(
            placeholder=t(
                "leaderboard.select.page_placeholder",
                locale,
                current=str(current_page),
                total=str(total_pages),
            ),
            min_values=1,
            max_values=1,
            options=options,
            row=4,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.current_page = int(self.values[0])
        await self.view.refresh(interaction)


# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------


class PreviousPageButton(discord.ui.Button["LeaderboardView"]):
    def __init__(self, *, disabled: bool = False, locale: str = "enUS") -> None:
        super().__init__(
            label=t("leaderboard.button.previous_page", locale),
            emoji="\u2b05\ufe0f",
            style=discord.ButtonStyle.secondary,
            row=0,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        if self.view.current_page > 1:
            self.view.current_page -= 1
        await self.view.refresh(interaction)


class NextPageButton(discord.ui.Button["LeaderboardView"]):
    def __init__(self, *, disabled: bool = False, locale: str = "enUS") -> None:
        super().__init__(
            label=t("leaderboard.button.next_page", locale),
            emoji="\u27a1\ufe0f",
            style=discord.ButtonStyle.secondary,
            row=0,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.current_page += 1
        await self.view.refresh(interaction)


class RankFilterButton(discord.ui.Button["LeaderboardView"]):
    def __init__(self, rank_filter: str | None = None, locale: str = "enUS") -> None:
        if rank_filter is None:
            label = t("leaderboard.button.all_ranks", locale)
            emoji = get_rank_emote("U")
            style = discord.ButtonStyle.secondary
        elif rank_filter == _RANKED_ONLY:
            label = t("leaderboard.button.ranked_only", locale)
            emoji = get_rank_emote("L")
            style = discord.ButtonStyle.primary
        else:
            label = t("leaderboard.button.rank_filter", locale, rank=rank_filter)
            emoji = get_rank_emote(rank_filter)
            style = discord.ButtonStyle.primary
        super().__init__(label=label, emoji=emoji, style=style, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        current = self.view.rank_filter
        try:
            idx = _RANK_CYCLE.index(current)
        except ValueError:
            idx = 0
        self.view.rank_filter = _RANK_CYCLE[(idx + 1) % len(_RANK_CYCLE)]
        self.view.current_page = 1
        await self.view.refresh(interaction)


class BestRaceOnlyButton(discord.ui.Button["LeaderboardView"]):
    def __init__(self, best_race_only: bool = False, locale: str = "enUS") -> None:
        super().__init__(
            label=t("leaderboard.button.best_race_only", locale),
            emoji="\u2705" if best_race_only else "\U0001f7e9",
            style=(
                discord.ButtonStyle.primary
                if best_race_only
                else discord.ButtonStyle.secondary
            ),
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.best_race_only = not self.view.best_race_only
        self.view.current_page = 1
        await self.view.refresh(interaction)


class ClearFiltersButton(discord.ui.Button["LeaderboardView"]):
    def __init__(self, locale: str = "enUS") -> None:
        super().__init__(
            label=t("leaderboard.button.clear_filters", locale),
            emoji="\U0001f5d1\ufe0f",
            style=discord.ButtonStyle.danger,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.race_filter = None
        self.view.country_page1_selection = []
        self.view.country_page2_selection = []
        self.view.rank_filter = None
        self.view.best_race_only = False
        self.view.current_page = 1
        await self.view.refresh(interaction)


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------


class LeaderboardView(discord.ui.View):
    def __init__(self, entries: list[dict], locale: str = "enUS") -> None:
        super().__init__(timeout=300)
        self._all_entries = entries
        self.locale: str = locale
        self.current_page: int = 1
        self.race_filter: list[str] | None = None
        self.country_page1_selection: list[str] = []
        self.country_page2_selection: list[str] = []
        self.rank_filter: str | None = None
        self.best_race_only: bool = False
        self._rebuild_components()

    @property
    def nationality_filter(self) -> list[str] | None:
        combined = self.country_page1_selection + self.country_page2_selection
        return combined or None

    def _filtered(self) -> list[dict]:
        return _apply_filters(
            self._all_entries,
            race_filter=self.race_filter,
            nationality_filter=self.nationality_filter,
            best_race_only=self.best_race_only,
            rank_filter=self.rank_filter,
        )

    def _total_pages(self, total: int) -> int:
        pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        return min(pages, 25)  # Discord dropdown limit

    def _rebuild_components(self) -> None:
        self.clear_items()
        filtered = self._filtered()
        total_pages = self._total_pages(len(filtered))
        loc = self.locale

        self.add_item(PreviousPageButton(disabled=self.current_page <= 1, locale=loc))
        self.add_item(
            NextPageButton(disabled=self.current_page >= total_pages, locale=loc)
        )
        self.add_item(RankFilterButton(self.rank_filter, locale=loc))
        self.add_item(BestRaceOnlyButton(self.best_race_only, locale=loc))
        self.add_item(ClearFiltersButton(locale=loc))
        self.add_item(RaceFilterSelect(self.race_filter, locale=loc))
        self.add_item(
            CountryFilterPage1Select(self.country_page1_selection, locale=loc)
        )
        self.add_item(
            CountryFilterPage2Select(self.country_page2_selection, locale=loc)
        )
        self.add_item(PageNavigationSelect(total_pages, self.current_page, locale=loc))

    def build_embed(self) -> LeaderboardEmbed:
        filtered = self._filtered()
        total_pages = self._total_pages(len(filtered))
        return LeaderboardEmbed(
            filtered,
            self.current_page,
            total_pages,
            len(filtered),
            race_filter=self.race_filter,
            nationality_filter=self.nationality_filter,
            best_race_only=self.best_race_only,
            rank_filter=self.rank_filter,
            locale=self.locale,
        )

    async def refresh(self, interaction: discord.Interaction) -> None:
        self._rebuild_components()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)


# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------


def register_leaderboard_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="leaderboard", description="View the MMR leaderboard")
    @app_commands.describe(game_mode="Game mode (default: 1v1)")
    @app_commands.choices(game_mode=GAME_MODE_CHOICES)
    @app_commands.check(check_if_accepted_tos)
    @app_commands.check(check_if_completed_setup)
    @app_commands.check(check_if_banned)
    @app_commands.check(check_if_dm)
    async def leaderboard_command(
        interaction: discord.Interaction,
        game_mode: str = "1v1",
    ) -> None:
        locale = get_player_locale(interaction.user.id)

        if game_mode != "1v1":
            await interaction.response.send_message(
                t(
                    "unsupported_game_mode_embed.description.1",
                    locale,
                    game_mode=game_mode,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        entries = await _ensure_leaderboard(interaction.user.id)
        view = LeaderboardView(entries, locale=locale)
        embed = view.build_embed()
        await interaction.followup.send(embed=embed, view=view)
