import io
import json
from typing import Any

import structlog
import discord
from discord import app_commands

from bot.components.embeds import (
    AdminMatchEmbed,
    AdminReplayDetailsEmbed,
    MatchNotFoundEmbed,
    UnsupportedGameModeEmbed,
)
from bot.core.config import BACKEND_URL, GAME_MODE_CHOICES
from bot.core.http import get_session
from bot.helpers.checks import check_if_admin

logger = structlog.get_logger(__name__)


# ----------------
# Internal helpers
# ----------------


async def _fetch_match(match_id: int) -> dict[str, Any]:
    async with get_session().get(
        f"{BACKEND_URL}/admin/matches_1v1/{match_id}"
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
    @app_commands.check(check_if_admin)
    @app_commands.choices(game_mode=GAME_MODE_CHOICES)
    async def match_command(
        interaction: discord.Interaction,
        match_id: int,
        game_mode: app_commands.Choice[str] = None,  # type: ignore[assignment]
    ) -> None:
        await interaction.response.defer()

        mode = game_mode.value if game_mode else "1v1"

        if mode != "1v1":
            await interaction.followup.send(embed=UnsupportedGameModeEmbed(mode))
            return

        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /match {match_id} (mode={mode})"
        )

        data = await _fetch_match(match_id)
        match = data.get("match")

        if match is None:
            await interaction.followup.send(embed=MatchNotFoundEmbed(match_id))
            return

        player_1 = data.get("player_1")
        player_2 = data.get("player_2")
        admin = data.get("admin")
        replays: list[dict[str, Any]] = data.get("replays") or []
        verifications: list[dict[str, Any] | None] = data.get("verification") or []
        replay_urls: list[str | None] = data.get("replay_urls") or []

        embeds: list[discord.Embed] = [
            AdminMatchEmbed(match, player_1, player_2, admin)
        ]

        for i, replay in enumerate(replays):
            verification = verifications[i] if i < len(verifications) else None
            url = replay_urls[i] if i < len(replay_urls) else None
            embeds.append(AdminReplayDetailsEmbed(i + 1, replay, verification, url))

        # Attach raw JSON state as a file.
        raw_state = {
            "match": match,
            "player_1": player_1,
            "player_2": player_2,
            "admin": admin,
            "replays": replays,
            "verification": verifications,
            "replay_urls": replay_urls,
        }
        json_bytes = json.dumps(
            raw_state, indent=2, ensure_ascii=False, default=str
        ).encode()
        file = discord.File(
            fp=io.BytesIO(json_bytes),
            filename=f"admin_match_{match_id}.json",
        )

        await interaction.followup.send(embeds=embeds, file=file)
