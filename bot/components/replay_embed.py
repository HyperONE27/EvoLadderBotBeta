"""
Replay embeds — shown after a replay is uploaded.

The embed always displays verification results regardless of the
``_ENABLE_REPLAY_VALIDATION`` flag in queue_command.py.  The flag is passed
as ``enforcement_enabled`` so the bottom status message reflects whether
those checks are actually enforced.
"""

from typing import Any

import discord

from bot.helpers.emotes import get_race_emote
from common.datetime_helpers import to_display


class ReplaySuccessEmbed(discord.Embed):
    """Full replay details embed shown after a successful replay parse."""

    def __init__(
        self,
        replay_data: dict[str, Any],
        verification_results: dict[str, Any] | None = None,
        enforcement_enabled: bool = True,
        auto_resolved: bool = False,
    ) -> None:
        p1_name: str = replay_data.get("player_1_name", "Player 1")
        p2_name: str = replay_data.get("player_2_name", "Player 2")
        p1_race_str: str = replay_data.get("player_1_race", "")
        p2_race_str: str = replay_data.get("player_2_race", "")
        winner_result: int = replay_data.get("result_int", 0)
        map_name: str = replay_data.get("map_name", "Unknown")
        duration_seconds: int = replay_data.get("game_duration_seconds", 0)
        observers: list[str] = replay_data.get("observers", [])

        p1_race_emote = get_race_emote(p1_race_str)
        p2_race_emote = get_race_emote(p2_race_str)

        # Winner
        if winner_result == 1:
            winner_text = f"🥇 {p1_race_emote} {p1_name}"
        elif winner_result == 2:
            winner_text = f"🥇 {p2_race_emote} {p2_name}"
        else:
            winner_text = "⚖️ Draw"

        # Duration
        minutes, seconds = divmod(duration_seconds, 60)
        duration_text = f"{minutes:02d}:{seconds:02d}"

        # Observers
        observers_text = (
            "⚠️ " + ", ".join(observers) if observers else "✅ No observers present"
        )

        # Map name — break before parenthetical note if present
        map_display = map_name.replace(" (", "\n(", 1) if "(" in map_name else map_name

        super().__init__(
            title="📄 Replay Details",
            description="Summary of the uploaded replay for the match.",
            color=discord.Color.light_grey(),
        )

        self.add_field(name="", value="\u3164", inline=False)

        self.add_field(
            name="⚔️ Matchup",
            value=f"**{p1_race_emote} {p1_name}** vs\n**{p2_race_emote} {p2_name}**",
            inline=True,
        )
        self.add_field(name="🏆 Result", value=winner_text, inline=True)
        self.add_field(name="🗺️ Map", value=map_display, inline=True)

        # Game start time
        replay_date_raw = replay_data.get("replay_time") or replay_data.get(
            "replay_date", ""
        )
        start_display = to_display(raw=replay_date_raw)
        if start_display != "—":
            self.add_field(
                name="🕒 Game Start Time",
                value=start_display,
                inline=True,
            )

        self.add_field(name="🕒 Game Duration", value=duration_text, inline=True)
        self.add_field(name="🔍 Observers", value=observers_text, inline=True)

        self.add_field(name="", value="\u3164", inline=False)

        if verification_results:
            verification_text = _format_verification(
                verification_results,
                enforcement_enabled=enforcement_enabled,
                auto_resolved=auto_resolved,
            )
            self.add_field(
                name="☑️ Replay Verification",
                value=verification_text,
                inline=False,
            )


class ReplayErrorEmbed(discord.Embed):
    """Red error embed for a replay parsing failure."""

    def __init__(self, error_message: str) -> None:
        super().__init__(
            title="❌ Replay Parsing Failed",
            description=(
                "The uploaded file could not be parsed as a valid SC2Replay.\n"
                "Please try again with a different file."
            ),
            color=discord.Color.red(),
        )
        self.add_field(
            name="Error Details",
            value=f"```{error_message[:1000]}```",
            inline=False,
        )


# ---------------------------------------------------------------------------
# Verification formatter
# ---------------------------------------------------------------------------


def _format_verification(
    results: dict[str, Any],
    enforcement_enabled: bool,
    auto_resolved: bool = False,
) -> str:
    lines: list[str] = []

    races_check = results.get("races", {})
    if races_check.get("success"):
        lines.append("- ✅ **Races Match:** Played races correspond to queued races.")
    else:
        expected = ", ".join(sorted(races_check.get("expected_races", [])))
        played = ", ".join(sorted(races_check.get("played_races", [])))
        lines.append(
            f"- ❌ **Races Mismatch:** Expected `{expected}`, but played `{played}`."
        )

    map_check = results.get("map", {})
    if map_check.get("success"):
        lines.append("- ✅ **Map Matches:** Correct map was used.")
    else:
        lines.append(
            f"- ❌ **Map Mismatch:** Expected `{map_check.get('expected_map')}`, "
            f"but played `{map_check.get('played_map')}`."
        )

    mod_check = results.get("mod", {})
    prefix = "✅" if mod_check.get("success") else "❌"
    lines.append(
        f"- {prefix} **{'Mod Valid' if mod_check.get('success') else 'Mod Invalid'}:** "
        f"{mod_check.get('message', '')}"
    )

    ts_check = results.get("timestamp", {})
    if ts_check.get("success"):
        diff = ts_check.get("time_difference_minutes")
        if diff is not None:
            lines.append(
                f"- ✅ **Timestamp Valid:** Match started within "
                f"{abs(diff):.1f} min of assignment."
            )
    else:
        if ts_check.get("error"):
            lines.append(
                f"- ❌ **Timestamp Invalid:** Could not verify. "
                f"Reason: `{ts_check['error']}`"
            )
        else:
            diff = ts_check.get("time_difference_minutes")
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

    obs_check = results.get("observers", {})
    if obs_check.get("success"):
        lines.append("- ✅ **No Observers:** No unauthorized observers detected.")
    else:
        names = ", ".join(obs_check.get("observers_found", []))
        lines.append(f"- ❌ **Observers Detected:** Unauthorized observers: `{names}`.")

    for key, label in (
        ("game_privacy", "Game Privacy Setting"),
        ("game_speed", "Game Speed Setting"),
        ("game_duration", "Game Duration Setting"),
        ("locked_alliances", "Locked Alliances Setting"),
    ):
        chk = results.get(key, {})
        if chk.get("success"):
            lines.append(f"- ✅ **{label}:** `{chk.get('found')}`")
        else:
            lines.append(
                f"- ❌ **{label}:** Expected `{chk.get('expected')}`, "
                f"but found `{chk.get('found')}`."
            )

    ai_check = results.get("ai_players", {})
    if ai_check:
        if not ai_check.get("ai_detected", False):
            lines.append("- ✅ **No AI Players:** Both players are human.")
        elif ai_check.get("success"):
            lines.append(
                "- ⚠️ **AI Player Detected:** Allowed (_ALLOW_AI_PLAYERS = True)."
            )
        else:
            names = ", ".join(ai_check.get("ai_player_names", []))
            lines.append(
                f"- ❌ **AI Player Detected:** _ALLOW_AI_PLAYERS = False; "
                f"an AI player was detected (`{names}`)."
            )

    # Overall summary
    all_ok = all(
        results.get(k, {}).get("success", False)
        for k in (
            "races",
            "map",
            "mod",
            "timestamp",
            "observers",
            "game_privacy",
            "game_speed",
            "game_duration",
            "locked_alliances",
            "ai_players",
        )
    )
    critical_failed = not races_check.get("success", True)

    lines.append("")

    if auto_resolved:
        lines.append(
            "✅ **Verification Complete:** All critical checks passed.\n"
            "✅ **Match auto-resolved** from replay data. No manual reporting needed."
        )
    elif all_ok:
        lines.append(
            "✅ **Verification Complete:** All checks passed.\n"
            "ℹ️ This embed is provided for informational purposes only. "
            "Please report the match result manually.\n"
            "🔓 Match reporting unlocked. Please report the result "
            "**using the dropdown menus above.**"
        )
    elif critical_failed and enforcement_enabled:
        lines.append(
            "❌ **Critical Validation Failure:**\n"
            "❌ We do not accept games played with the incorrect races, map, or mod.\n"
            "🔒 Result reporting has been locked. "
            "Please contact an admin to nullify this match."
        )
    else:
        action = (
            "🔓 Match reporting unlocked. Please report the result "
            "**using the dropdown menus above.**"
            if not (enforcement_enabled and critical_failed)
            else "🔒 Result reporting has been locked."
        )
        lines.append(
            "⚠️ **Verification Issues:** One or more checks failed.\n"
            "⚠️ Please review the issues above.\n" + action
        )

    return "\n".join(lines)
