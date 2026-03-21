"""Throwaway test script: parse all 2v2 replays and simulate verification.

Writes detailed results to debug_2v2_parsing.txt.
Run from project root: python test_2v2_parser.py
"""

import os
import sys
import types

# Ensure project root is on the path so imports work.
sys.path.insert(0, os.path.dirname(__file__))

# Stub backend.core.config so we can import the verifier without .env
_fake_config = types.ModuleType("backend.core.config")
_fake_config.ALLOW_AI_PLAYERS = True  # type: ignore[attr-defined]
_fake_config.EXPECTED_LOBBY_SETTINGS = {  # type: ignore[attr-defined]
    "duration": "Infinite",
    "locked_alliances": "Yes",
    "privacy": "Normal",
    "speed": "Faster",
}
_fake_config.REPLAY_TIMESTAMP_WINDOW_MINUTES = 60  # type: ignore[attr-defined]
sys.modules["backend.core.config"] = _fake_config

from backend.algorithms.replay_parser import parse_replay_2v2  # noqa: E402
from backend.algorithms.replay_verifier import verify_replay_2v2  # noqa: E402

REPLAYS_DIR = os.path.join(os.path.dirname(__file__), "replays")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "debug_2v2_parsing.txt")

# Fake match row for verification simulation — uses the parsed replay's own
# values so we can see what verification looks like in the "happy path" case.
# Mirror match detection and setting checks will still be meaningful.


def _build_fake_match(parsed: dict) -> dict:
    """Build a Matches2v2Row-like dict from parsed replay data.

    Uses the replay's own values as the "expected" match, so race/map checks
    pass by construction.  This lets us observe the verification structure
    and catch issues with settings, observers, AI detection, and mirror matches.
    """
    return {
        "team_1_player_1_discord_uid": 1,
        "team_1_player_2_discord_uid": 2,
        "team_2_player_1_discord_uid": 3,
        "team_2_player_2_discord_uid": 4,
        "team_1_player_1_name": parsed["team_1_player_1_name"],
        "team_1_player_2_name": parsed["team_1_player_2_name"],
        "team_2_player_1_name": parsed["team_2_player_1_name"],
        "team_2_player_2_name": parsed["team_2_player_2_name"],
        "team_1_player_1_race": parsed["team_1_player_1_race"],
        "team_1_player_2_race": parsed["team_1_player_2_race"],
        "team_2_player_1_race": parsed["team_2_player_1_race"],
        "team_2_player_2_race": parsed["team_2_player_2_race"],
        "team_1_mmr": 1500,
        "team_2_mmr": 1500,
        "map_name": parsed["map_name"],
        "server_name": "USW",
        "assigned_at": parsed["replay_time"],
        "match_result": None,
    }


def _find_replays(root: str) -> list[str]:
    """Recursively find all .SC2Replay files."""
    found = []
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if f.endswith(".SC2Replay"):
                found.append(os.path.join(dirpath, f))
    found.sort()
    return found


def main() -> None:
    replay_files = _find_replays(REPLAYS_DIR)
    if not replay_files:
        print(f"No .SC2Replay files found in {REPLAYS_DIR}")
        return

    print(f"Found {len(replay_files)} replays. Parsing...")

    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("2v2 REPLAY PARSING + VERIFICATION DEBUG OUTPUT")
    lines.append("=" * 80)
    lines.append("")

    parse_ok = 0
    parse_fail = 0

    for filepath in replay_files:
        rel_path = os.path.relpath(filepath, os.path.dirname(__file__))
        lines.append("-" * 80)
        lines.append(f"FILE: {rel_path}")
        lines.append("-" * 80)

        with open(filepath, "rb") as f:
            replay_bytes = f.read()

        # --- Parse ---
        parsed = parse_replay_2v2(replay_bytes)

        if parsed.get("error"):
            lines.append(f"  PARSE ERROR: {parsed['error']}")
            lines.append("")
            parse_fail += 1
            continue

        parse_ok += 1

        lines.append("")
        lines.append("  [PARSED RESULT]")
        lines.append(f"    replay_hash:    {parsed['replay_hash']}")
        lines.append(f"    replay_time:    {parsed['replay_time']}")
        lines.append(f"    map_name:       {parsed['map_name']}")
        lines.append(
            f"    match_result:   {parsed['match_result']} (int: {parsed['result_int']})"
        )
        lines.append(f"    duration:       {parsed['game_duration_seconds']}s")
        lines.append(f"    observers:      {parsed['observers']}")
        lines.append("")
        lines.append("    Team 1:")
        lines.append(
            f"      P1: {parsed['team_1_player_1_name']:20s}  race={parsed['team_1_player_1_race']:15s}  handle={parsed['team_1_player_1_handle']}"
        )
        lines.append(
            f"      P2: {parsed['team_1_player_2_name']:20s}  race={parsed['team_1_player_2_race']:15s}  handle={parsed['team_1_player_2_handle']}"
        )
        lines.append("    Team 2:")
        lines.append(
            f"      P1: {parsed['team_2_player_1_name']:20s}  race={parsed['team_2_player_1_race']:15s}  handle={parsed['team_2_player_1_handle']}"
        )
        lines.append(
            f"      P2: {parsed['team_2_player_2_name']:20s}  race={parsed['team_2_player_2_race']:15s}  handle={parsed['team_2_player_2_handle']}"
        )
        lines.append("")
        lines.append(f"    game_privacy:          {parsed['game_privacy']}")
        lines.append(f"    game_speed:            {parsed['game_speed']}")
        lines.append(f"    game_duration_setting: {parsed['game_duration_setting']}")
        lines.append(f"    locked_alliances:      {parsed['locked_alliances']}")
        lines.append(
            f"    cache_handles:         {len(parsed['cache_handles'])} handle(s)"
        )

        # --- Verify ---
        # Use a fake match built from the parsed data itself so we can see
        # what the verification result structure looks like.
        fake_match = _build_fake_match(parsed)

        # We don't have real mods/maps data, so pass empty dicts.
        # Mod and map checks will fail, but that's expected — the point is
        # to see race checks, mirror detection, settings, observers, and AI.
        verification = verify_replay_2v2(parsed, fake_match, {}, {})

        lines.append("")
        lines.append("  [VERIFICATION RESULT]")

        for key, val in verification.items():
            if isinstance(val, dict):
                success = val.get("success", "N/A")
                marker = (
                    "PASS" if success is True else "FAIL" if success is False else "N/A"
                )
                lines.append(f"    {key}: [{marker}]")
                for k, v in val.items():
                    if k != "success":
                        lines.append(f"      {k}: {v}")
            elif isinstance(val, bool):
                lines.append(f"    {key}: {val}")
            else:
                lines.append(f"    {key}: {val}")

        # --- Autoreport simulation ---
        lines.append("")
        lines.append("  [AUTOREPORT SIMULATION]")
        mirror = verification.get("mirror_match", False)
        races_t1_ok = verification.get("races_team_1", {}).get("success", False)
        races_t2_ok = verification.get("races_team_2", {}).get("success", False)

        if mirror:
            lines.append(
                "    BLOCKED: Mirror match detected — cannot determine team mapping."
            )
            lines.append("    Fallback: manual reporting required.")
        elif not races_t1_ok or not races_t2_ok:
            lines.append("    BLOCKED: Race verification failed for at least one team.")
            lines.append("    Fallback: manual reporting required.")
        else:
            lines.append(f"    WOULD AUTOREPORT: {parsed['match_result']}")

        lines.append("")

    # --- Summary ---
    lines.append("=" * 80)
    lines.append("SUMMARY")
    lines.append("=" * 80)
    lines.append(f"  Total replays:   {len(replay_files)}")
    lines.append(f"  Parsed OK:       {parse_ok}")
    lines.append(f"  Parse errors:    {parse_fail}")
    lines.append("")

    output = "\n".join(lines)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"Done. Results written to {OUTPUT_FILE}")
    print(f"  Parsed OK: {parse_ok}, Errors: {parse_fail}")


if __name__ == "__main__":
    main()
