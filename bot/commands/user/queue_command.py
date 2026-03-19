import asyncio
import time
from typing import Any

import structlog

import discord
from discord import app_commands

from bot.components.embeds import (
    MatchAbortAckEmbed,
    MatchConfirmedEmbed,
    MatchInfoEmbed,
    QueueErrorEmbed,
    QueueSearchingEmbed,
    QueueSetupEmbed,
)
from bot.core.config import (
    BACKEND_URL,
    CONFIRMATION_TIMEOUT,
    CURRENT_SEASON,
    MAX_MAP_VETOES,
    QUEUE_SEARCHING_HEARTBEAT_SECONDS,
)
from bot.core.dependencies import get_cache
from bot.core.http import get_session
from bot.helpers.checks import (
    check_if_accepted_tos,
    check_if_banned,
    check_if_completed_setup,
    check_if_dm,
    check_if_queueing,
    AlreadyQueueingError,
)
from bot.helpers.emotes import get_game_emote, get_race_emote
from common.lookups.map_lookups import get_maps
from common.lookups.race_lookups import get_bw_race_codes, get_races, get_sc2_race_codes

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
            for code in get_bw_race_codes()
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
            for code in get_sc2_race_codes()
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
        maps = get_maps(game_mode="1v1", season=CURRENT_SEASON) or {}
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
            placeholder=f"Select maps to veto (max {MAX_MAP_VETOES})...",
            min_values=0,
            max_values=min(MAX_MAP_VETOES, len(options)),
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
            try:
                await check_if_queueing(interaction)
            except AlreadyQueueingError as e:
                await interaction.response.send_message(str(e), ephemeral=True)
                return
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
        embed = QueueSetupEmbed(self.bw_race, self.sc2_race, self.map_vetoes)
        await interaction.response.edit_message(embed=embed, view=new_view)


class _CancelQueueButton(discord.ui.Button):
    def __init__(
        self,
        discord_user_id: int,
        bw_race: str | None,
        sc2_race: str | None,
        map_vetoes: list[str],
    ) -> None:
        super().__init__(
            label="Cancel Queue",
            emoji="✖️",
            style=discord.ButtonStyle.danger,
            row=0,
        )
        self.discord_user_id = discord_user_id
        self.bw_race = bw_race
        self.sc2_race = sc2_race
        self.map_vetoes = map_vetoes

    async def callback(self, interaction: discord.Interaction) -> None:
        await _leave_queue(
            interaction,
            self.discord_user_id,
            self.bw_race,
            self.sc2_race,
            self.map_vetoes,
        )


class QueueSearchingView(discord.ui.View):
    def __init__(
        self,
        interaction: discord.Interaction,
        discord_user_id: int,
        bw_race: str | None,
        sc2_race: str | None,
        map_vetoes: list[str],
    ) -> None:
        super().__init__(timeout=None)
        self._interaction = interaction
        self._heartbeat_task: asyncio.Task[None] | None = None
        self.add_item(
            _CancelQueueButton(discord_user_id, bw_race, sc2_race, map_vetoes)
        )

    async def start_heartbeat(self) -> None:
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        """Update the searching embed's timestamp at the 15th second of every minute."""

        while True:
            try:
                now = time.time()
                # Sleep until the 15th second of the next minute.
                current_minute_start = (now // 60) * 60
                next_beat = current_minute_start + 15
                if next_beat <= now:
                    next_beat += 60
                await asyncio.sleep(next_beat - now)

                # Fetch fresh stats and rebuild the embed.
                stats: dict | None = None
                try:
                    async with get_session().get(
                        f"{BACKEND_URL}/queue_1v1/stats"
                    ) as resp:
                        stats = await resp.json()
                except Exception:
                    pass

                await self._interaction.edit_original_response(
                    embed=QueueSearchingEmbed(stats),
                )
            except asyncio.CancelledError:
                return
            except Exception:
                logger.warning("queue_heartbeat_error", exc_info=True)
                await asyncio.sleep(QUEUE_SEARCHING_HEARTBEAT_SECONDS)

    def stop_heartbeat(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()


class MatchFoundView(discord.ui.View):
    def __init__(self, match_id: int, match_data: dict) -> None:
        super().__init__(timeout=CONFIRMATION_TIMEOUT)
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

            if resp.status >= 400:
                await interaction.followup.send(
                    embed=QueueErrorEmbed(
                        data.get("detail") or "Failed to submit report."
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

        if resp.status >= 400:
            await interaction.edit_original_response(
                embed=QueueErrorEmbed(data.get("detail") or "Failed to join queue."),
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

        searching_view = QueueSearchingView(
            interaction, discord_user_id, bw_race, sc2_race, map_vetoes
        )
        await interaction.edit_original_response(
            embed=QueueSearchingEmbed(stats),
            view=searching_view,
        )
        await searching_view.start_heartbeat()

        # Store a reference to this message so the WS listener can edit it
        # when a match is found (stops the timer and removes the cancel button).
        try:
            msg = await interaction.original_response()
            get_cache().active_searching_messages[discord_user_id] = msg
            get_cache().active_searching_views[discord_user_id] = searching_view
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


async def _leave_queue(
    interaction: discord.Interaction,
    discord_user_id: int,
    bw_race: str | None,
    sc2_race: str | None,
    map_vetoes: list[str],
) -> None:
    await interaction.response.defer()
    try:
        async with get_session().delete(
            f"{BACKEND_URL}/queue_1v1/leave",
            json={"discord_uid": interaction.user.id},
        ) as resp:
            data = await resp.json()

        if resp.status >= 400:
            await interaction.followup.send(
                embed=QueueErrorEmbed(data.get("detail") or "Failed to leave queue."),
                ephemeral=True,
            )
            return

        setup_view = QueueSetupView(discord_user_id, bw_race, sc2_race, map_vetoes)
        embed = QueueSetupEmbed(bw_race, sc2_race, map_vetoes)
        await interaction.edit_original_response(embed=embed, view=setup_view)

        # Stop the heartbeat and clear cached references.
        try:
            cache = get_cache()
            cache.active_searching_messages.pop(interaction.user.id, None)
            view = cache.active_searching_views.pop(interaction.user.id, None)
            if view is not None and hasattr(view, "stop_heartbeat"):
                view.stop_heartbeat()
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
            await resp.json()

        if resp.status >= 400:
            await interaction.followup.send(
                embed=QueueErrorEmbed("Failed to confirm match."),
                ephemeral=True,
            )
            return

        # Always show "waiting for opponent" — the WS listener sends a NEW
        # message with match details once both players have confirmed.
        embed = MatchConfirmedEmbed(match_id)
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

        if resp.status >= 400:
            await interaction.followup.send(
                embed=QueueErrorEmbed(data.get("detail") or "Failed to abort match."),
                ephemeral=True,
            )
            return

        await interaction.edit_original_response(
            embed=MatchAbortAckEmbed(),
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
    @app_commands.check(check_if_accepted_tos)
    @app_commands.check(check_if_completed_setup)
    @app_commands.check(check_if_queueing)
    @app_commands.check(check_if_banned)
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

        embed = QueueSetupEmbed(bw_race, sc2_race, map_vetoes)
        view = QueueSetupView(
            discord_user_id=interaction.user.id,
            bw_race=bw_race,
            sc2_race=sc2_race,
            map_vetoes=map_vetoes,
        )
        await interaction.followup.send(embed=embed, view=view)
