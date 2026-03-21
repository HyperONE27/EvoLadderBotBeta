"""
Pure replay verification: compares parsed replay data against expected match
parameters and returns a VerificationResult dict.
"""

from typing import Any

from backend.core.config import (
    ALLOW_AI_PLAYERS,
    EXPECTED_LOBBY_SETTINGS,
    REPLAY_TIMESTAMP_WINDOW_MINUTES,
)
from common.datetime_helpers import ensure_utc


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def verify_replay_1v1(
    parsed: dict[str, Any],
    match: dict[str, Any],
    mods: dict[str, Any],
    maps: dict[str, Any],
) -> dict[str, Any]:
    """
    Verify a parsed 1v1 replay against a match record.

    Args:
        parsed: dict returned by ``parse_replay_1v1()``.
        match:  ``Matches1v1Row`` dict from the backend state.
        mods:   ``state_manager.mods`` dict (from mods.json).
        maps:   ``state_manager.maps`` dict (from maps.json, season-level).

    Returns:
        dict with keys: races, map, mod, timestamp, observers, ai_players,
        game_privacy, game_speed, game_duration, locked_alliances.
    """
    result: dict[str, Any] = {}

    # --- Races ---
    expected_races = {match["player_1_race"], match["player_2_race"]}
    played_races = {parsed["player_1_race"], parsed["player_2_race"]}
    result["races"] = {
        "success": expected_races == played_races,
        "expected_races": sorted(expected_races),
        "played_races": sorted(played_races),
    }

    # --- Map ---
    # match["map_name"] is the short name (e.g. "Celestial Enclave"); the replay
    # contains the full name (e.g. "Celestial Enclave LE").  Resolve via maps data.
    short_name: str = match["map_name"]
    map_entry = maps.get(short_name, {})
    expected_map: str = map_entry.get("name", short_name)
    played_map: str = parsed.get("map_name", "")
    result["map"] = {
        "success": expected_map == played_map,
        "expected_map": expected_map,
        "played_map": played_map,
    }

    # --- Mod ---
    result["mod"] = _verify_mod(parsed.get("cache_handles", []), mods)

    # --- Timestamp ---
    result["timestamp"] = _verify_timestamp(
        parsed.get("replay_time", ""), match.get("assigned_at")
    )

    # --- Observers ---
    observers_found: list[str] = parsed.get("observers", [])
    result["observers"] = {
        "success": len(observers_found) == 0,
        "observers_found": observers_found,
    }

    # --- AI Players ---
    p1_name: str = parsed.get("player_1_name", "")
    p2_name: str = parsed.get("player_2_name", "")
    ai_names = [n for n in (p1_name, p2_name) if _is_ai_player(n)]
    ai_detected = len(ai_names) > 0
    result["ai_players"] = {
        "success": ALLOW_AI_PLAYERS or not ai_detected,
        "ai_detected": ai_detected,
        "ai_player_names": ai_names,
    }

    # --- Game settings ---
    for key, config_key, result_key in (
        ("game_privacy", "privacy", "game_privacy"),
        ("game_speed", "speed", "game_speed"),
        ("game_duration_setting", "duration", "game_duration"),
        ("locked_alliances", "locked_alliances", "locked_alliances"),
    ):
        expected_val: str = EXPECTED_LOBBY_SETTINGS[config_key]
        found_val: str = parsed.get(key, "")
        result[result_key] = {
            "success": found_val == expected_val,
            "expected": expected_val,
            "found": found_val,
        }

    return result


def verify_replay_2v2(
    parsed: dict[str, Any],
    match: dict[str, Any],
    mods: dict[str, Any],
    maps: dict[str, Any],
) -> dict[str, Any]:
    """
    Verify a parsed 2v2 replay against a match record.

    Args:
        parsed: dict returned by ``parse_replay_2v2()``.
        match:  ``Matches2v2Row`` dict from the backend state.
        mods:   ``state_manager.mods`` dict (from mods.json).
        maps:   ``state_manager.maps`` dict (from maps.json, season-level).

    Returns:
        dict with keys: races_team_1, races_team_2, mirror_match, map, mod,
        timestamp, observers, ai_players, game_privacy, game_speed,
        game_duration, locked_alliances.
    """
    result: dict[str, Any] = {}

    # --- Races (set comparison per team) ---
    expected_t1 = {match["team_1_player_1_race"], match["team_1_player_2_race"]}
    played_t1 = {parsed["team_1_player_1_race"], parsed["team_1_player_2_race"]}
    result["races_team_1"] = {
        "success": expected_t1 == played_t1,
        "expected_races": sorted(expected_t1),
        "played_races": sorted(played_t1),
    }

    expected_t2 = {match["team_2_player_1_race"], match["team_2_player_2_race"]}
    played_t2 = {parsed["team_2_player_1_race"], parsed["team_2_player_2_race"]}
    result["races_team_2"] = {
        "success": expected_t2 == played_t2,
        "expected_races": sorted(expected_t2),
        "played_races": sorted(played_t2),
    }

    # --- Mirror match detection ---
    # If both teams have the same race composition, we cannot reliably
    # determine which replay team corresponds to which match team.
    # Autoreporting must be blocked in this case.
    is_mirror = expected_t1 == expected_t2
    result["mirror_match"] = is_mirror

    # --- Map ---
    short_name: str = match["map_name"]
    map_entry = maps.get(short_name, {})
    expected_map: str = map_entry.get("name", short_name)
    played_map: str = parsed.get("map_name", "")
    result["map"] = {
        "success": expected_map == played_map,
        "expected_map": expected_map,
        "played_map": played_map,
    }

    # --- Mod ---
    result["mod"] = _verify_mod(parsed.get("cache_handles", []), mods)

    # --- Timestamp ---
    result["timestamp"] = _verify_timestamp(
        parsed.get("replay_time", ""), match.get("assigned_at")
    )

    # --- Observers ---
    observers_found: list[str] = parsed.get("observers", [])
    result["observers"] = {
        "success": len(observers_found) == 0,
        "observers_found": observers_found,
    }

    # --- AI Players ---
    player_names = [
        parsed.get("team_1_player_1_name", ""),
        parsed.get("team_1_player_2_name", ""),
        parsed.get("team_2_player_1_name", ""),
        parsed.get("team_2_player_2_name", ""),
    ]
    ai_names = [n for n in player_names if _is_ai_player(n)]
    ai_detected = len(ai_names) > 0
    result["ai_players"] = {
        "success": ALLOW_AI_PLAYERS or not ai_detected,
        "ai_detected": ai_detected,
        "ai_player_names": ai_names,
    }

    # --- Game settings ---
    for key, config_key, result_key in (
        ("game_privacy", "privacy", "game_privacy"),
        ("game_speed", "speed", "game_speed"),
        ("game_duration_setting", "duration", "game_duration"),
        ("locked_alliances", "locked_alliances", "locked_alliances"),
    ):
        expected_val: str = EXPECTED_LOBBY_SETTINGS[config_key]
        found_val: str = parsed.get(key, "")
        result[result_key] = {
            "success": found_val == expected_val,
            "expected": expected_val,
            "found": found_val,
        }

    return result


def _resolve_mirror_match_names(
    parsed: dict[str, Any],
    match: dict[str, Any],
) -> dict[str, Any] | None:
    """Attempt to resolve mirror match ambiguity via player display names.

    Cross-references the four player names from the parsed replay against the
    expected player names in the match record to determine which replay team
    corresponds to which match team.

    Returns a resolution dict if names unambiguously resolve, None otherwise.

    # TODO: implement name-based mirror match resolution
    """
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_ai_player(name: str) -> bool:
    """Return True if the name contains characters typical of AI player names.

    AI names tend to include parentheses, periods, or digits 1-9
    (e.g. "A.I. 3 (Insane)").
    """
    return any(c in name for c in "().123456789")


def _verify_mod(cache_handles: list[str], mods: dict[str, Any]) -> dict[str, Any]:
    multi = mods.get("multi")
    if not multi:
        return {
            "success": False,
            "message": "SC: Evo Complete mod data not found.",
        }

    all_known: set[str] = set()
    for key in (
        "am_handles",
        "eu_handles",
        "as_handles",
        "am_artmod_handles",
        "eu_artmod_handles",
        "as_artmod_handles",
    ):
        all_known.update(multi.get(key, []))

    matching = set(cache_handles) & all_known
    if matching:
        return {
            "success": True,
            "message": (
                f"SC: Evo Complete mod detected ({len(matching)} matching handle(s))."
            ),
        }
    return {
        "success": False,
        "message": "SC: Evo Complete mod not detected in cache handles.",
    }


def _verify_timestamp(replay_time_raw: Any, assigned_at: Any) -> dict[str, Any]:
    try:
        replay_dt = ensure_utc(replay_time_raw)
        if replay_dt is None:
            return {
                "success": False,
                "error": "No replay time available.",
                "time_difference_minutes": None,
            }

        assigned_dt = ensure_utc(assigned_at)
        if assigned_dt is None:
            return {
                "success": False,
                "error": "No match assignment time available.",
                "time_difference_minutes": None,
            }

        diff_minutes = (replay_dt - assigned_dt).total_seconds() / 60
        in_window = 0 <= diff_minutes <= REPLAY_TIMESTAMP_WINDOW_MINUTES

        return {
            "success": in_window,
            "time_difference_minutes": diff_minutes,
            "error": None,
        }

    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "time_difference_minutes": None,
        }
