import io
import json
from typing import Any

import structlog
import discord
from discord import app_commands

from bot.components.embeds import (
    AdminMatchEmbed,
    AdminMatchEmbed2v2,
    AdminReplayDetailsEmbed,
    MatchNotFoundEmbed,
)
from bot.components.views import AdminReplayToggleView
from bot.core.config import BACKEND_URL, GAME_MODE_CHOICES
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from bot.helpers.checks import check_admin

logger = structlog.get_logger(__name__)


# ----------------
# Internal helpers
# ----------------


async def _fetch_match_1v1(match_id: int, caller_uid: int) -> dict[str, Any]:
    async with get_session().get(
        f"{BACKEND_URL}/admin/matches_1v1/{match_id}",
        params={"caller_uid": caller_uid},
    ) as response:
        data: dict[str, Any] = await response.json()
        return data


async def _fetch_match_2v2(match_id: int, caller_uid: int) -> dict[str, Any]:
    async with get_session().get(
        f"{BACKEND_URL}/admin/matches_2v2/{match_id}",
        params={"caller_uid": caller_uid},
    ) as response:
        data: dict[str, Any] = await response.json()
        return data


# --------------------
# Command registration
# --------------------


def register_admin_match_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="match", description="[Admin] View full match details and replays"
    )
    @app_commands.choices(game_mode=GAME_MODE_CHOICES)
    async def match_command(
        interaction: discord.Interaction,
        game_mode: app_commands.Choice[str],
        match_id: int,
    ) -> None:
        await interaction.response.defer()
        await check_admin(interaction)

        mode = game_mode.value
        locale = get_player_locale(interaction.user.id)

        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /match {match_id} (mode={mode})"
        )

        if mode == "2v2":
            await _handle_match_2v2(interaction, match_id, locale)
        else:
            await _handle_match_1v1(interaction, match_id, locale)


async def _handle_match_1v1(
    interaction: discord.Interaction, match_id: int, locale: str
) -> None:
    data = await _fetch_match_1v1(match_id, interaction.user.id)
    match = data.get("match")

    if match is None:
        await interaction.followup.send(
            embed=MatchNotFoundEmbed(match_id, locale=locale)
        )
        return

    player_1 = data.get("player_1")
    player_2 = data.get("player_2")
    admin = data.get("admin")
    replays: list[dict[str, Any]] = data.get("replays") or []
    verifications: list[dict[str, Any] | None] = data.get("verification") or []
    replay_urls: list[str | None] = data.get("replay_urls") or []

    match_embed = AdminMatchEmbed(match, player_1, player_2, admin, locale=locale)

    raw_state = {
        "match": match,
        "player_1": player_1,
        "player_2": player_2,
        "admin": admin,
        "replays": replays,
        "verification": verifications,
        "replay_urls": replay_urls,
        "chat_history": data.get("chat_history"),
    }
    json_bytes = json.dumps(
        raw_state, indent=2, ensure_ascii=False, default=str
    ).encode()
    file = discord.File(
        fp=io.BytesIO(json_bytes),
        filename=f"admin_match_{match_id}.json",
    )

    # Filter to only the current replays referenced by the match row.
    # Re-uploads append new rows to replays_1v1; the match row always
    # points to the latest via player_N_replay_row_id.
    ref_ids = {
        match.get("player_1_replay_row_id"),
        match.get("player_2_replay_row_id"),
    } - {None}
    if ref_ids:
        filtered = [
            (r, v, u)
            for r, v, u in zip(replays, verifications, replay_urls)
            if r.get("id") in ref_ids
        ]
        replays = [t[0] for t in filtered]
        verifications = [t[1] for t in filtered]
        replay_urls = [t[2] for t in filtered]

    if len(replays) >= 2:
        view = AdminReplayToggleView(
            match_embed, replays, verifications, replay_urls, locale=locale
        )
        await interaction.followup.send(
            embeds=view.build_embeds(), file=file, view=view
        )
    elif len(replays) == 1:
        verification = verifications[0] if verifications else None
        url = replay_urls[0] if replay_urls else None
        embeds = [
            match_embed,
            AdminReplayDetailsEmbed(1, replays[0], verification, url, locale=locale),
        ]
        await interaction.followup.send(embeds=embeds, file=file)
    else:
        await interaction.followup.send(embeds=[match_embed], file=file)


async def _handle_match_2v2(
    interaction: discord.Interaction, match_id: int, locale: str
) -> None:
    data = await _fetch_match_2v2(match_id, interaction.user.id)
    match = data.get("match")

    if match is None:
        await interaction.followup.send(
            embed=MatchNotFoundEmbed(match_id, locale=locale)
        )
        return

    players: dict[str, dict[str, Any] | None] = {
        "team_1_player_1": data.get("team_1_player_1"),
        "team_1_player_2": data.get("team_1_player_2"),
        "team_2_player_1": data.get("team_2_player_1"),
        "team_2_player_2": data.get("team_2_player_2"),
    }
    admin = data.get("admin")

    embeds: list[discord.Embed] = [
        AdminMatchEmbed2v2(match, players, admin, locale=locale)
    ]

    raw_state = {
        "match": match,
        **players,
        "admin": admin,
        "chat_history": data.get("chat_history"),
    }
    json_bytes = json.dumps(
        raw_state, indent=2, ensure_ascii=False, default=str
    ).encode()
    file = discord.File(
        fp=io.BytesIO(json_bytes),
        filename=f"admin_match_2v2_{match_id}.json",
    )

    await interaction.followup.send(embeds=embeds, file=file)
