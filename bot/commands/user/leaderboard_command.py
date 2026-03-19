import structlog

import discord
from discord import app_commands

from bot.core.config import (
    BACKEND_URL,
    EXCLUDE_INACTIVE_PLAYERS_FROM_LETTER,
    GAME_MODE_CHOICES,
)
from bot.core.dependencies import get_cache
from bot.core.http import get_session
from bot.helpers.checks import (
    check_if_accepted_tos,
    check_if_banned,
    check_if_completed_setup,
    check_if_dm,
)
from bot.helpers.emotes import get_flag_emote, get_race_emote, get_rank_emote
from common.lookups.race_lookups import get_bw_race_codes, get_races, get_sc2_race_codes

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PAGE_SIZE = 40
_PLAYERS_PER_FIELD = 5

_RANK_CYCLE: list[str | None] = [None, "S", "A", "B", "C", "D", "E", "F"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _race_display(race_code: str) -> str:
    race = get_races().get(race_code)
    return race["short_name"] if race else race_code


async def _ensure_leaderboard() -> list[dict]:
    """Return the cached leaderboard, fetching from the backend if empty."""
    cache = get_cache()
    if cache.leaderboard_1v1:
        return cache.leaderboard_1v1

    try:
        async with get_session().get(f"{BACKEND_URL}/leaderboard_1v1") as resp:
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

    if rank_filter:
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
    ) -> None:
        super().__init__(title="Leaderboard", color=discord.Color.gold())

        # Filter summary
        parts: list[str] = []
        if race_filter:
            parts.append(
                "**Race:** `" + ", ".join(_race_display(r) for r in race_filter) + "`"
            )
        if nationality_filter:
            parts.append("**Nationality:** `" + ", ".join(nationality_filter) + "`")
        if rank_filter:
            parts.append(f"**Rank:** `{rank_filter}`")
        if best_race_only:
            parts.append("**Best Race Only**")
        if parts:
            self.add_field(name="", value="\n".join(parts), inline=False)

        # Leaderboard rows
        start = (page - 1) * _PAGE_SIZE
        page_entries = entries[start : start + _PAGE_SIZE]

        if not page_entries:
            self.add_field(name="Leaderboard", value="No players found.", inline=False)
        else:
            chunks: list[str] = []
            for i in range(0, len(page_entries), _PLAYERS_PER_FIELD):
                chunk = page_entries[i : i + _PLAYERS_PER_FIELD]
                lines: list[str] = []
                for entry in chunk:
                    rank_emote = get_rank_emote(entry["letter_rank"])
                    race_emote = get_race_emote(entry["race"])
                    flag_emote = get_flag_emote(entry["nationality"] or "XX")
                    if EXCLUDE_INACTIVE_PLAYERS_FROM_LETTER:
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
                    name=f"Leaderboard ({pair_start}-{pair_end})",
                    value=chunks[i],
                    inline=True,
                )
                if i + 1 < len(chunks):
                    self.add_field(name="\u200b", value=chunks[i + 1], inline=True)
                if i + 2 < len(chunks):
                    self.add_field(name=" ", value=" ", inline=False)

        self.set_footer(
            text=f"Page {page}/{total_pages} \u2022 {total_players} players"
        )


# ---------------------------------------------------------------------------
# Selects
# ---------------------------------------------------------------------------


class RaceFilterSelect(discord.ui.Select["LeaderboardView"]):
    def __init__(self, selected: list[str] | None = None) -> None:
        selected = selected or []
        options: list[discord.SelectOption] = []
        all_codes = get_bw_race_codes() + get_sc2_race_codes()
        for code in all_codes:
            race = get_races().get(code)
            if race is None:
                continue
            options.append(
                discord.SelectOption(
                    label=race["name"],
                    value=code,
                    emoji=get_race_emote(code),
                    default=code in selected,
                )
            )
        super().__init__(
            placeholder="Filter by race...",
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


class NationalityFilterSelect(discord.ui.Select["LeaderboardView"]):
    """Country filter — shows top countries from the leaderboard data."""

    def __init__(
        self, entries: list[dict], selected: list[str] | None = None, *, row: int
    ) -> None:
        selected = selected or []

        # Build list of nationalities present in the leaderboard, sorted by frequency.
        freq: dict[str, int] = {}
        for e in entries:
            nat = e.get("nationality") or ""
            if nat:
                freq[nat] = freq.get(nat, 0) + 1
        sorted_nats = sorted(freq, key=lambda n: freq[n], reverse=True)[:25]

        options = [
            discord.SelectOption(
                label=code,
                value=code,
                emoji=get_flag_emote(code),
                default=code in selected,
            )
            for code in sorted_nats
        ]

        if not options:
            options = [discord.SelectOption(label="No countries", value="_none")]

        super().__init__(
            placeholder="Filter by nationality...",
            min_values=0,
            max_values=len(options),
            options=options,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        values = [v for v in self.values if v != "_none"]
        self.view.nationality_filter = values or None
        self.view.current_page = 1
        await self.view.refresh(interaction)


class PageNavigationSelect(discord.ui.Select["LeaderboardView"]):
    def __init__(self, total_pages: int, current_page: int) -> None:
        options = [
            discord.SelectOption(
                label=f"Page {p}",
                value=str(p),
                default=p == current_page,
            )
            for p in range(1, total_pages + 1)
        ]
        super().__init__(
            placeholder=f"Page {current_page}/{total_pages}",
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
    def __init__(self, *, disabled: bool = False) -> None:
        super().__init__(
            label="Previous Page",
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
    def __init__(self, *, disabled: bool = False) -> None:
        super().__init__(
            label="Next Page",
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
    def __init__(self, rank_filter: str | None = None) -> None:
        if rank_filter is None:
            label = "All Ranks"
            emoji = get_rank_emote("U")
            style = discord.ButtonStyle.secondary
        else:
            label = f"{rank_filter}-Rank"
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
    def __init__(self, best_race_only: bool = False) -> None:
        super().__init__(
            label="Best Race Only",
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
    def __init__(self) -> None:
        super().__init__(
            label="Clear All Filters",
            emoji="\U0001f5d1\ufe0f",
            style=discord.ButtonStyle.danger,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.race_filter = None
        self.view.nationality_filter = None
        self.view.rank_filter = None
        self.view.best_race_only = False
        self.view.current_page = 1
        await self.view.refresh(interaction)


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------


class LeaderboardView(discord.ui.View):
    def __init__(self, entries: list[dict]) -> None:
        super().__init__(timeout=300)
        self._all_entries = entries
        self.current_page: int = 1
        self.race_filter: list[str] | None = None
        self.nationality_filter: list[str] | None = None
        self.rank_filter: str | None = None
        self.best_race_only: bool = False
        self._rebuild_components()

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

        self.add_item(PreviousPageButton(disabled=self.current_page <= 1))
        self.add_item(NextPageButton(disabled=self.current_page >= total_pages))
        self.add_item(RankFilterButton(self.rank_filter))
        self.add_item(BestRaceOnlyButton(self.best_race_only))
        self.add_item(ClearFiltersButton())
        self.add_item(RaceFilterSelect(self.race_filter))
        self.add_item(
            NationalityFilterSelect(self._all_entries, self.nationality_filter, row=2)
        )
        self.add_item(PageNavigationSelect(total_pages, self.current_page))

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
        if game_mode != "1v1":
            await interaction.response.send_message(
                "Only 1v1 leaderboard is currently available.", ephemeral=True
            )
            return

        await interaction.response.defer()

        entries = await _ensure_leaderboard()
        view = LeaderboardView(entries)
        embed = view.build_embed()
        await interaction.followup.send(embed=embed, view=view)
