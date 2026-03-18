import io
import json
from datetime import datetime
from typing import Any

import structlog
import discord
from discord import app_commands

from bot.core.config import BACKEND_URL
from bot.core.http import get_session
from bot.helpers.checks import check_if_admin
from bot.helpers.emotes import get_flag_emote, get_race_emote
from common.datetime_helpers import to_discord_timestamp, to_display
from common.lookups.region_lookups import get_game_server_by_code

logger = structlog.get_logger(__name__)

# ----------
# Constants
# ----------

GAME_MODE_CHOICES = [
    app_commands.Choice(name="1v1", value="1v1"),
    app_commands.Choice(name="2v2", value="2v2"),
    app_commands.Choice(name="FFA", value="ffa"),
]

_REPORT_LABELS: dict[str | None, str] = {
    "player_1_win": "Player 1 Won",
    "player_2_win": "Player 2 Won",
    "draw": "Draw",
    "invalidated": "Invalidated",
    None: "Not Reported",
}

# ----------
# Helpers
# ----------


def _player_prefix(race: str, nationality: str | None) -> str:
    """Build flag/race prefix for a player."""
    parts: list[str] = []
    if nationality:
        parts.append(str(get_flag_emote(nationality)))
    try:
        parts.append(get_race_emote(race))
    except ValueError:
        parts.append("🎮")
    return " ".join(parts)


def _result_display(result: str | None, p1_name: str, p2_name: str) -> str:
    if result == "player_1_win":
        return f"🏆 **{p1_name}** won"
    if result == "player_2_win":
        return f"🏆 **{p2_name}** won"
    if result == "draw":
        return "⚖️ **Draw**"
    if result == "invalidated":
        return "❌ **Invalidated**"
    return "⏳ **In Progress**"


def _format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


def _server_display(server_code: str | None) -> str:
    """Resolve server code to full name, falling back to the code itself."""
    if not server_code:
        return "Unknown"
    server = get_game_server_by_code(server_code)
    if server:
        return f"{server['name']} ({server_code})"
    return server_code


# ----------
# Embeds
# ----------


class MatchNotFoundEmbed(discord.Embed):
    def __init__(self, match_id: int) -> None:
        super().__init__(
            title="❌ Match Not Found",
            description=f"No match found with ID `{match_id}`.",
            color=discord.Color.red(),
        )


class AdminMatchEmbed(discord.Embed):
    """Main admin match overview — full matches_1v1 row data."""

    def __init__(
        self,
        match: dict[str, Any],
        player_1: dict[str, Any] | None,
        player_2: dict[str, Any] | None,
        admin: dict[str, Any] | None,
    ) -> None:
        match_id = match.get("id", "?")
        result = match.get("match_result")

        if result is None:
            color = discord.Color.blue()
        elif result == "invalidated":
            color = discord.Color.dark_grey()
        else:
            color = discord.Color.green()

        p1_name = match.get("player_1_name") or "Unknown"
        p2_name = match.get("player_2_name") or "Unknown"
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
            title=f"🔍 Admin Match #{match_id} State",
            description=(
                f"{p1_prefix} **{p1_name}** (MMR: {p1_mmr})"
                f"  vs  "
                f"{p2_prefix} **{p2_name}** (MMR: {p2_mmr})"
            ),
            color=color,
        )

        # --- Result ---
        self.add_field(
            name="",
            value=(
                f"**Result:** {_result_display(result, p1_name, p2_name)}\n"
                f"**Player 1 UID:** `{p1_uid}`\n"
                f"**Player 2 UID:** `{p2_uid}`"
            ),
            inline=False,
        )

        # --- Original Player Reports | Admin Resolved ---
        p1_report = _REPORT_LABELS.get(
            match.get("player_1_report"), match.get("player_1_report") or "Not Reported"
        )
        p2_report = _REPORT_LABELS.get(
            match.get("player_2_report"), match.get("player_2_report") or "Not Reported"
        )
        reports_text = f"**{p1_name}:** {p1_report}\n**{p2_name}:** {p2_report}"

        admin_intervened = match.get("admin_intervened", False)
        if admin_intervened:
            admin_uid = match.get("admin_discord_uid")
            admin_username = admin.get("discord_username") if admin else None
            if admin_username:
                resolved_text = f"✅ Yes\n{admin_username} (`{admin_uid}`)"
            else:
                resolved_text = f"✅ Yes\n`{admin_uid}`"
        else:
            resolved_text = "❌ No"

        self.add_field(
            name="📊 Original Player Reports", value=reports_text, inline=True
        )
        self.add_field(name="🛡️ Admin Resolved", value=resolved_text, inline=True)

        # --- MMR Changes ---
        p1_change = match.get("player_1_mmr_change")
        p2_change = match.get("player_2_mmr_change")
        if p1_change is not None or p2_change is not None:
            p1_c = p1_change or 0
            p2_c = p2_change or 0
            p1_new = p1_mmr + p1_c
            p2_new = p2_mmr + p2_c
            mmr_text = (
                f"**{p1_name}:** `{p1_c:+d}` ({p1_mmr} → {p1_new})\n"
                f"**{p2_name}:** `{p2_c:+d}` ({p2_mmr} → {p2_new})"
            )
            self.add_field(name="📈 MMR Changes", value=mmr_text, inline=False)

        # --- Match Info ---
        map_name = match.get("map_name") or "Unknown"
        server_code = match.get("server_name")
        info_text = (
            f"**Map:** `{map_name}`\n**Server:** `{_server_display(server_code)}`"
        )
        info_text += (
            f"\n**Assigned:** {to_discord_timestamp(raw=match.get('assigned_at'))}"
        )
        if match.get("completed_at"):
            info_text += f"\n**Completed:** {to_discord_timestamp(raw=match.get('completed_at'))}"
        self.add_field(name="🗺️ Match Info", value=info_text, inline=False)

        # --- Raw Match Data (full matches_1v1 row) ---
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
                # Show just the filename or NULL
                raw[key] = val.rsplit("/", 1)[-1] if "/" in val else val
            else:
                raw[key] = val

        raw_json = json.dumps(raw, indent=2, ensure_ascii=False)
        if len(raw_json) > 950:
            raw_json = raw_json[:950] + "\n..."
        self.add_field(
            name="📋 Raw Match Data",
            value=f"```json\n{raw_json}\n```",
            inline=False,
        )

        # --- Replay Status ---
        p1_replay = match.get("player_1_replay_path")
        p2_replay = match.get("player_2_replay_path")
        p1_status = "✅ Uploaded" if p1_replay else "❌ No"
        p2_status = "✅ Uploaded" if p2_replay else "❌ No"
        replay_text = f"**{p1_name}:** {p1_status}\n**{p2_name}:** {p2_status}"
        self.add_field(name="🎬 Replay Status", value=replay_text, inline=False)


class AdminReplayDetailsEmbed(discord.Embed):
    """Per-player replay details — mirrors the player-facing ReplaySuccessEmbed
    format with full verification from replay_embed.py."""

    def __init__(
        self,
        player_num: int,
        replay: dict[str, Any],
        verification: dict[str, Any] | None,
        replay_url: str | None,
    ) -> None:
        super().__init__(
            title=f"Player #{player_num} Replay Details",
            description="Summary of the uploaded replay for the match.",
            color=discord.Color.light_grey(),
        )

        p1_name = replay.get("player_1_name") or "Player 1"
        p2_name = replay.get("player_2_name") or "Player 2"
        p1_race = replay.get("player_1_race") or ""
        p2_race = replay.get("player_2_race") or ""
        result_str = replay.get("match_result") or "?"
        map_name = replay.get("map_name") or "Unknown"
        duration = replay.get("game_duration_seconds") or 0
        observers: list[str] = replay.get("observers") or []

        # Race emotes
        try:
            p1_emote = get_race_emote(p1_race)
        except ValueError:
            p1_emote = "🎮"
        try:
            p2_emote = get_race_emote(p2_race)
        except ValueError:
            p2_emote = "🎮"

        # Result display
        if result_str in ("player_1_win", "1"):
            result_display = f"🏆 {p1_name}"
        elif result_str in ("player_2_win", "2"):
            result_display = f"🏆 {p2_name}"
        elif result_str in ("draw", "0"):
            result_display = "⚖️ Draw"
        else:
            result_display = str(result_str)

        # Map name — break before parenthetical note if present
        map_display = map_name.replace(" (", "\n(", 1) if "(" in map_name else map_name

        # Spacer
        self.add_field(name="", value="\u3164", inline=False)

        # --- Row 1: Matchup | Result | Map ---
        self.add_field(
            name="⚔️ Matchup",
            value=f"**{p1_emote} {p1_name}** vs\n**{p2_emote} {p2_name}**",
            inline=True,
        )
        self.add_field(name="🏆 Result", value=result_display, inline=True)
        self.add_field(name="🗺️ Map", value=map_display, inline=True)

        # --- Row 2: Start Time | Duration | Observers ---
        # Use the same full-format timestamp as the player-facing embed
        start_time = to_display(raw=replay.get("replay_time"))
        self.add_field(name="🕒 Game Start Time", value=start_time, inline=True)
        self.add_field(
            name="🕒 Game Duration",
            value=_format_duration(duration),
            inline=True,
        )

        obs_text = (
            f"⚠️ {', '.join(observers)}" if observers else "✅ No observers present"
        )
        self.add_field(name="🔍 Observers", value=obs_text, inline=True)

        # Spacer
        self.add_field(name="", value="\u3164", inline=False)

        # --- Replay Verification ---
        if verification:
            self.add_field(
                name="☑️ Replay Verification",
                value=_format_verification(verification),
                inline=False,
            )

        # --- Download link ---
        if replay_url:
            self.add_field(
                name="📥 Download",
                value=f"[Replay File]({replay_url})",
                inline=False,
            )


class UnsupportedGameModeEmbed(discord.Embed):
    def __init__(self, game_mode: str) -> None:
        super().__init__(
            title="🚧 Unsupported Game Mode",
            description=f"`{game_mode}` is not yet supported. Only `1v1` is currently available.",
            color=discord.Color.orange(),
        )


# ----------
# Verification formatter
# ----------


def _format_verification(v: dict[str, Any]) -> str:
    """Build the full verification checklist string — matches the player-facing
    format from replay_embed.py."""
    lines: list[str] = []

    # Races
    races = v.get("races", {})
    if races.get("success"):
        lines.append("- ✅ **Races Match:** Played races correspond to queued races.")
    else:
        expected = ", ".join(sorted(races.get("expected_races", [])))
        played = ", ".join(sorted(races.get("played_races", [])))
        lines.append(
            f"- ❌ **Races Mismatch:** Expected `{expected}`, but played `{played}`."
        )

    # Map
    map_check = v.get("map", {})
    if map_check.get("success"):
        lines.append("- ✅ **Map Matches:** Correct map was used.")
    else:
        lines.append(
            f"- ❌ **Map Mismatch:** Expected `{map_check.get('expected_map')}`, "
            f"but played `{map_check.get('played_map')}`."
        )

    # Mod
    mod = v.get("mod", {})
    prefix = "✅" if mod.get("success") else "❌"
    lines.append(
        f"- {prefix} **{'Mod Valid' if mod.get('success') else 'Mod Invalid'}:** "
        f"{mod.get('message', '')}"
    )

    # Timestamp
    ts = v.get("timestamp", {})
    if ts.get("success"):
        diff = ts.get("time_difference_minutes")
        if diff is not None:
            lines.append(
                f"- ✅ **Timestamp Valid:** Match started within "
                f"{abs(diff):.1f} min of assignment."
            )
    else:
        if ts.get("error"):
            lines.append(
                f"- ❌ **Timestamp Invalid:** Could not verify. Reason: `{ts['error']}`"
            )
        else:
            diff = ts.get("time_difference_minutes")
            if diff is not None:
                if diff < 0:
                    lines.append(
                        f"- ❌ **Timestamp Invalid:** Match started "
                        f"{abs(diff):.1f} min **before** assignment."
                    )
                else:
                    lines.append(
                        f"- ❌ **Timestamp Invalid:** Match started "
                        f"{diff:.1f} min **after** assignment (exceeds window)."
                    )
            else:
                lines.append("- ❌ **Timestamp Invalid:** Unknown error.")

    # Observers
    obs = v.get("observers", {})
    if obs.get("success"):
        lines.append("- ✅ **No Observers:** No unauthorized observers detected.")
    else:
        names = ", ".join(obs.get("observers_found", []))
        lines.append(f"- ❌ **Observers Detected:** Unauthorized observers: `{names}`.")

    # Game settings
    for key, label in (
        ("game_privacy", "Game Privacy Setting"),
        ("game_speed", "Game Speed Setting"),
        ("game_duration", "Game Duration Setting"),
        ("locked_alliances", "Locked Alliances Setting"),
    ):
        check = v.get(key, {})
        if check.get("success"):
            lines.append(f"- ✅ **{label}:** `{check.get('found')}`")
        else:
            lines.append(
                f"- ❌ **{label}:** Expected `{check.get('expected')}`, "
                f"but found `{check.get('found')}`."
            )

    # Critical failure summary
    critical_fail = any(
        not v.get(k, {}).get("success", True) for k in ("races", "map", "mod")
    )

    if critical_fail:
        lines.append("")
        lines.append(
            "⚠️ **Critical Validation Failure:**\n"
            "We do not accept games played with the incorrect races, map, or mod. "
            "Result reporting has been locked. Please contact an admin to nullify this match."
        )

    return "\n".join(lines)


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
