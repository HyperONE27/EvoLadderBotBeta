import time

import structlog

import discord
from discord import app_commands

from bot.core.config import BACKEND_URL
from bot.core.http import get_session
from bot.helpers.checks import check_if_dm
from bot.helpers.emotes import get_game_emote, get_race_emote
from common.lookups.map_lookups import get_maps
from common.lookups.race_lookups import get_races

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BW_RACES = ["bw_terran", "bw_zerg", "bw_protoss"]
_SC2_RACES = ["sc2_terran", "sc2_zerg", "sc2_protoss"]
_MAX_MAP_VETOES = 4
_QUICKSTART_URL = "https://rentry.co/evoladderbot-quickstartguide"
_NUMBER_EMOTES = [":one:", ":two:", ":three:", ":four:"]


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
        title="Matchmaking Queue",
        color=discord.Color.blue(),
    )

    # Quick start guide warning
    embed.add_field(
        name="NEW PLAYERS START HERE",
        value=f"**QUICK START GUIDE:** [READ THIS BEFORE YOUR FIRST MATCH!]({_QUICKSTART_URL})\n",
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
    def __init__(self, stats: dict | None = None) -> None:
        bw_only = stats.get("bw_only", 0) if stats else 0
        sc2_only = stats.get("sc2_only", 0) if stats else 0
        both = stats.get("both", 0) if stats else 0
        now = time.time()
        next_search = int((now // 60 + 1) * 60)

        super().__init__(
            title="Searching...",
            description=(
                "The queue is searching for a game.\n\n"
                f"- Next search: <t:{next_search}:R>\n"
                "- Search interval: 60 seconds\n"
                "- Current players queueing:\n"
                f"  - Brood War: {bw_only}\n"
                f"  - StarCraft II: {sc2_only}\n"
                f"  - Both: {both}"
            ),
            color=discord.Color.blue(),
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
            title=f"Match #{match_id} Found!",
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
            title=f"Match #{match_id} Confirmed!",
            description="Both players confirmed. Match details are now available below.",
            color=discord.Color.green(),
        )


class MatchConfirmedEmbed(discord.Embed):
    def __init__(self, match_data: dict) -> None:
        match_id = match_data.get("id", "?")
        p1_name = match_data.get("player_1_name", "Player 1")
        p2_name = match_data.get("player_2_name", "Player 2")
        p1_race = match_data.get("player_1_race", "")
        p2_race = match_data.get("player_2_race", "")
        p1_mmr = match_data.get("player_1_mmr", "?")
        p2_mmr = match_data.get("player_2_mmr", "?")
        map_name = match_data.get("map_name", "Unknown")
        server_name = match_data.get("server_name", "Unknown")

        p1_display = (
            f"{get_race_emote(p1_race)} {p1_name} ({p1_mmr})" if p1_race else p1_name
        )
        p2_display = (
            f"{get_race_emote(p2_race)} {p2_name} ({p2_mmr})" if p2_race else p2_name
        )

        title = f"Match #{match_id}:\n{p1_display} vs {p2_display}"

        super().__init__(
            title=title,
            color=discord.Color.teal(),
        )

        self.add_field(
            name="**Match Information:**",
            value=(
                f"- Map: `{map_name}`\n"
                f"- Server: `{server_name}`\n"
                f"- In-Game Channel: `SCEvoLadder`"
            ),
            inline=False,
        )

        self.add_field(
            name="**Match Result:**",
            value="- Result: `Not selected`",
            inline=False,
        )


class MatchReportedEmbed(discord.Embed):
    def __init__(self, report: str) -> None:
        super().__init__(
            title="Report Submitted",
            description=(
                f"You reported: **{_report_display(report)}**\n\n"
                "Waiting for your opponent to report..."
            ),
            color=discord.Color.gold(),
        )


class MatchCompletedEmbed(discord.Embed):
    def __init__(self, match_data: dict) -> None:
        match_id = match_data.get("id", "?")
        result = match_data.get("match_result", "unknown")
        p1_name = match_data.get("player_1_name", "Player 1")
        p2_name = match_data.get("player_2_name", "Player 2")
        p1_mmr = match_data.get("player_1_mmr", 0)
        p2_mmr = match_data.get("player_2_mmr", 0)
        p1_change = match_data.get("player_1_mmr_change")
        p2_change = match_data.get("player_2_mmr_change")

        if result == "invalidated":
            color = discord.Color.orange()
            title = f"Match #{match_id} Result Conflict"
        else:
            color = discord.Color.gold()
            title = f"Match #{match_id} Result Finalized"

        super().__init__(title=title, color=color)

        self.add_field(
            name="**Result:**", value=f"`{_report_display(result)}`", inline=True
        )

        if p1_change is not None and p2_change is not None:
            p1_sign = "+" if p1_change >= 0 else ""
            p2_sign = "+" if p2_change >= 0 else ""
            p1_new = p1_mmr + p1_change
            p2_new = p2_mmr + p2_change
            self.add_field(
                name="**MMR Changes:**",
                value=(
                    f"- {p1_name}: `{p1_sign}{p1_change} ({p1_mmr} -> {p1_new})`\n"
                    f"- {p2_name}: `{p2_sign}{p2_change} ({p2_mmr} -> {p2_new})`"
                ),
                inline=True,
            )


class MatchAbortedEmbed(discord.Embed):
    def __init__(self, match_data: dict | None = None, reason: str = "aborted") -> None:
        match_id = match_data.get("id", "?") if match_data else "?"
        result = match_data.get("match_result", reason) if match_data else reason
        title_action = "Abandoned" if result == "abandoned" else "Aborted"
        super().__init__(
            title=f"Match #{match_id} {title_action}",
            description=f"The match was {title_action.lower()}. No MMR changes were applied.",
            color=discord.Color.red(),
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
    def __init__(self, match_id: int, p1_name: str, p2_name: str) -> None:
        super().__init__(timeout=None)
        self.match_id = match_id
        self.add_item(MatchReportSelect(match_id, p1_name, p2_name))

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

            # Report recorded — show waiting embed. The WS listener will handle
            # the final result notification as a separate message.
            await interaction.edit_original_response(
                embed=MatchReportedEmbed(report), view=None
            )

        except Exception:
            logger.exception("Failed to submit match report")
            await interaction.followup.send(
                embed=QueueErrorEmbed("An unexpected error occurred."),
                ephemeral=True,
            )


# ---------------------------------------------------------------------------
# HTTP action helpers
# ---------------------------------------------------------------------------


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
        async with get_session().post(
            f"{BACKEND_URL}/queue_1v1/join",
            json={
                "discord_uid": discord_user_id,
                "discord_username": interaction.user.name,
                "bw_race": bw_race,
                "sc2_race": sc2_race,
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
            title=f"Match #{match_id} — Confirmed!",
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

        await interaction.edit_original_response(embed=MatchAbortedEmbed(), view=None)

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
