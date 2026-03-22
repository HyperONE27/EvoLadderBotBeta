"""
Pure, CPU-bound SC2Replay parsing algorithm.

Designed to be called via ProcessPoolExecutor so it never blocks the event loop.
The function is importable at module level and has no side effects.
"""

import io
import logging
import os
import sys
from datetime import timezone
from typing import Any

import sc2reader  # type: ignore[import-untyped]
import xxhash

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_RESULT_INT_TO_STR_1V1: dict[int, str] = {
    0: "draw",
    1: "player_1_win",
    2: "player_2_win",
}

_RESULT_INT_TO_STR_2V2: dict[int, str] = {
    -1: "indeterminate",
    0: "draw",
    1: "team_1_win",
    2: "team_2_win",
}

# Hard-coded sc2reader race name → ladder race code mapping.
# Alias resolution via the races.json lookup is NOT done here because this
# function runs in a worker process that may not have the lookup modules
# initialised.  All localised aliases from races.json are listed explicitly so
# that replays recorded on non-English clients map correctly.
_RACE_MAP: dict[str, str] = {
    # English (sc2reader default)
    "Terran": "sc2_terran",
    "Zerg": "sc2_zerg",
    "Protoss": "sc2_protoss",
    "BW Terran": "bw_terran",
    "BW Zerg": "bw_zerg",
    "BW Protoss": "bw_protoss",
    # Korean
    "테란": "sc2_terran",
    "저그": "sc2_zerg",
    "토스": "sc2_protoss",
    "스1 테란": "bw_terran",
    "스1 저그": "bw_zerg",
    "스1 토스": "bw_protoss",
    # Chinese (Simplified)
    "人类": "sc2_terran",
    "异虫": "sc2_zerg",
    "星灵": "sc2_protoss",
    "SC1人类": "bw_terran",
    "SC1异虫": "bw_zerg",
    "SC1星灵": "bw_protoss",
    # Russian
    "Терраны": "sc2_terran",
    "Зерги": "sc2_zerg",
    "Протоссы": "sc2_protoss",
}


def _fix_race(race: str) -> str:
    return _RACE_MAP.get(race, race)


def _find_toon_handles(data: Any) -> list[str]:
    """Recursively search for non-empty toon_handle values."""
    handles: list[str] = []

    def _traverse(obj: Any) -> None:
        if isinstance(obj, dict):
            val = obj.get("toon_handle")
            if val and val != "":
                handles.append(val)
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    _traverse(v)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    _traverse(item)

    _traverse(data)
    return handles


def _extract_cache_handles(replay: Any) -> list[str]:
    if not hasattr(replay, "raw_data"):
        return []

    # Primary location
    if "replay.details.backup" in replay.raw_data:
        raw = replay.raw_data["replay.details.backup"].get("cache_handles", [])
        handles = [str(h) for h in raw]
        if handles:
            return handles

    # Fallback location
    if "replay.initData.backup" in replay.raw_data:
        game_desc = replay.raw_data["replay.initData.backup"].get(
            "game_description", {}
        )
        raw = game_desc.get("cache_handles", [])
        return [str(h) for h in raw]

    return []


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def parse_replay_1v1(replay_bytes: bytes) -> dict[str, Any]:
    """
    Parse a 1v1 .SC2Replay and return a dict with all fields needed for
    the ``replays_1v1`` table (except ``replay_path``, ``uploaded_at``, and
    ``matches_1v1_id``, which are assigned by the caller at upload time).

    Returns:
        On success: ``{"error": None, "replay_hash": ..., ...}``
        On failure: ``{"error": "<message>"}``
    """
    # Silence sc2reader noise in the worker process.
    logging.getLogger("sc2reader").setLevel(logging.CRITICAL)
    devnull = open(os.devnull, "w")
    original_stderr = sys.stderr
    sys.stderr = devnull

    try:
        replay = sc2reader.load_replay(io.BytesIO(replay_bytes), load_level=4)

        if len(replay.players) != 2:
            return {"error": f"Expected 2 players, got {len(replay.players)}."}

        # --- Hash (64-bit xxhash, hex string) ---
        replay_hash: str = xxhash.xxh64(replay_bytes).hexdigest()

        # --- Cache handles ---
        cache_handles = _extract_cache_handles(replay)
        if not cache_handles:
            return {"error": "No cache_handles found in replay data."}

        # --- Players ---
        p1 = replay.players[0]
        p2 = replay.players[1]
        player_1_race = _fix_race(p1.play_race)
        player_2_race = _fix_race(p2.play_race)

        # --- Winner ---
        winner = replay.winner
        if winner is None:
            remaining = {p.name for p in replay.players}
            for msg in replay.messages:
                if msg.text.endswith("was defeated!"):
                    remaining.discard(msg.text.replace(" was defeated!", ""))
            if len(remaining) == 1:
                winner_name = next(iter(remaining))
                for p in replay.players:
                    if p.name == winner_name:
                        winner = p
                        break

        if winner is None:
            result_int = 0
        else:
            winner_str = str(winner)
            if "Player 1" in winner_str:
                result_int = 1
            elif "Player 2" in winner_str:
                result_int = 2
            else:
                result_int = 0

        # --- Toon handles ---
        toon_handles = _find_toon_handles(replay.raw_data)
        player_1_handle = toon_handles[0] if len(toon_handles) >= 1 else ""
        player_2_handle = toon_handles[1] if len(toon_handles) >= 2 else ""

        # --- Duration (seconds, Faster speed) ---
        duration = 0
        if hasattr(replay, "game_events"):
            for event in replay.game_events:
                if event.name == "PlayerLeaveEvent":
                    if event.player and not event.player.is_observer:
                        duration = int(round(event.second / 1.4))
                        break
        if duration == 0 and hasattr(replay, "game_length"):
            duration = int(round(replay.game_length.seconds))

        # --- Observers ---
        observers: list[str] = [o.name for o in replay.observers]

        # --- Replay date ---
        # sc2reader produces naive datetimes; replay metadata is always UTC.
        if hasattr(replay, "date") and replay.date:
            dt = replay.date
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            replay_time: str = dt.isoformat()
        else:
            replay_time = "1970-01-01T00:00:00+00:00"

        return {
            "error": None,
            "replay_hash": replay_hash,
            "replay_time": replay_time,
            "player_1_name": p1.name,
            "player_2_name": p2.name,
            "player_1_race": player_1_race,
            "player_2_race": player_2_race,
            "result_int": result_int,
            "match_result": _RESULT_INT_TO_STR_1V1[result_int],
            "player_1_handle": player_1_handle,
            "player_2_handle": player_2_handle,
            "observers": observers,
            "map_name": replay.map_name,
            "game_duration_seconds": duration,
            "game_privacy": replay.attributes[16]["Game Privacy"],
            "game_speed": replay.attributes[16]["Game Speed"],
            "game_duration_setting": replay.attributes[16]["Game Duration"],
            "locked_alliances": replay.attributes[16]["Locked Alliances"],
            "cache_handles": cache_handles,
        }

    except Exception as exc:
        return {"error": f"sc2reader failed: {type(exc).__name__}: {exc}"}

    finally:
        sys.stderr = original_stderr
        devnull.close()


_EARLY_LEAVE_SENTINEL = "early_leave"


def _infer_winner_2v2(replay: Any) -> Any:
    """Attempt to infer the winning team when replay.winner is None.

    Scans chat messages for "was defeated!" to determine which team lost.
    If both players from one team were defeated, the other team wins.

    If only one non-observer PlayerLeaveEvent exists and no defeat messages
    are found, the replay was likely recorded by a player who left early.
    Returns ``_EARLY_LEAVE_SENTINEL`` so the caller can set result_int = -1.
    """
    # Build name → team mapping.
    team_by_name: dict[str, Any] = {}
    for team in replay.teams:
        for player in team.players:
            team_by_name[player.name] = team

    # Collect defeated player names from chat messages.
    defeated_names: set[str] = set()
    for msg in replay.messages:
        if msg.text.endswith("was defeated!"):
            name = msg.text.replace(" was defeated!", "")
            defeated_names.add(name)

    # Check if both players from one team were defeated.
    defeated_by_team: dict[int, int] = {}
    for name in defeated_names:
        team = team_by_name.get(name)
        if team is not None:
            team_num = getattr(team, "number", None)
            if team_num is not None:
                defeated_by_team[team_num] = defeated_by_team.get(team_num, 0) + 1

    for team_num, count in defeated_by_team.items():
        if count >= 2:
            # Both players on this team were defeated — the other team wins.
            winning_team_num = 1 if team_num == 2 else 2
            for team in replay.teams:
                if getattr(team, "number", None) == winning_team_num:
                    return team

    # No full-team defeat found.  Check if this is an early-leaver replay:
    # only 1 non-observer PlayerLeaveEvent and no defeat messages.
    if not defeated_names:
        leave_count = 0
        if hasattr(replay, "game_events"):
            for event in replay.game_events:
                if event.name == "PlayerLeaveEvent":
                    if event.player and not event.player.is_observer:
                        leave_count += 1
        if leave_count <= 1:
            return _EARLY_LEAVE_SENTINEL

    return None


def parse_replay_2v2(replay_bytes: bytes) -> dict[str, Any]:
    """
    Parse a 2v2 .SC2Replay and return a dict with all fields needed for
    the ``replays_2v2`` table (except ``replay_path``, ``uploaded_at``, and
    ``matches_2v2_id``, which are assigned by the caller at upload time).

    Players are assigned to teams via ``replay.teams``, not by positional
    index in ``replay.players``.  Toon handles are in player-number (pid)
    order and mapped to team slots via each player's ``.pid`` attribute.

    Returns:
        On success: ``{"error": None, "replay_hash": ..., ...}``
        On failure: ``{"error": "<message>"}``
    """
    logging.getLogger("sc2reader").setLevel(logging.CRITICAL)
    devnull = open(os.devnull, "w")
    original_stderr = sys.stderr
    sys.stderr = devnull

    try:
        replay = sc2reader.load_replay(io.BytesIO(replay_bytes), load_level=4)

        # --- Guards ---
        if len(replay.players) != 4:
            return {"error": f"Expected 4 players, got {len(replay.players)}."}
        if getattr(replay, "type", None) != "2v2":
            return {
                "error": f"Expected 2v2 game type, got '{getattr(replay, 'type', 'unknown')}'."
            }
        if len(replay.teams) != 2:
            return {"error": f"Expected 2 teams, got {len(replay.teams)}."}

        # --- Hash ---
        replay_hash: str = xxhash.xxh64(replay_bytes).hexdigest()

        # --- Cache handles ---
        cache_handles = _extract_cache_handles(replay)
        if not cache_handles:
            return {"error": "No cache_handles found in replay data."}

        # --- Team / player extraction ---
        # replay.teams[0] = Team 1, replay.teams[1] = Team 2.
        # Each team's .players list has 2 Player objects.
        team_1_players = replay.teams[0].players
        team_2_players = replay.teams[1].players

        if len(team_1_players) != 2 or len(team_2_players) != 2:
            return {
                "error": (
                    f"Expected 2 players per team, got "
                    f"{len(team_1_players)} and {len(team_2_players)}."
                )
            }

        t1p1 = team_1_players[0]
        t1p2 = team_1_players[1]
        t2p1 = team_2_players[0]
        t2p2 = team_2_players[1]

        # --- Races ---
        t1p1_race = _fix_race(t1p1.play_race)
        t1p2_race = _fix_race(t1p2.play_race)
        t2p1_race = _fix_race(t2p1.play_race)
        t2p2_race = _fix_race(t2p2.play_race)

        # --- Winner ---
        winner = replay.winner
        if winner is None:
            winner = _infer_winner_2v2(replay)

        if winner is None:
            return {
                "error": (
                    "Could not determine the winner of this game. "
                    "This is unexpected — please report this replay."
                )
            }
        elif winner == _EARLY_LEAVE_SENTINEL:
            result_int = -1
        else:
            team_number = getattr(winner, "number", None)
            if team_number == 1:
                result_int = 1
            elif team_number == 2:
                result_int = 2
            else:
                return {
                    "error": (
                        "Could not determine the winner of this game. "
                        "This is unexpected — please report this replay."
                    )
                }

        # --- Toon handles ---
        # Handles are in pid order (handles[0] = pid 1, handles[1] = pid 2, etc.)
        # but team composition is arbitrary (Team 1 may be pids 1+4, not 1+2).
        # Build a pid → handle mapping and look up each team member's handle.
        toon_handles = _find_toon_handles(replay.raw_data)
        if len(toon_handles) < 4:
            pid_to_handle: dict[int, str] = {}
        else:
            pid_to_handle = {p.pid: toon_handles[p.pid - 1] for p in replay.players}

        t1p1_handle = pid_to_handle.get(t1p1.pid, "")
        t1p2_handle = pid_to_handle.get(t1p2.pid, "")
        t2p1_handle = pid_to_handle.get(t2p1.pid, "")
        t2p2_handle = pid_to_handle.get(t2p2.pid, "")

        # --- Duration (seconds, Faster speed) ---
        duration = 0
        if hasattr(replay, "game_events"):
            for event in replay.game_events:
                if event.name == "PlayerLeaveEvent":
                    if event.player and not event.player.is_observer:
                        duration = int(round(event.second / 1.4))
                        break
        if duration == 0 and hasattr(replay, "game_length"):
            duration = int(round(replay.game_length.seconds))

        # --- Observers ---
        observers: list[str] = [o.name for o in replay.observers]

        # --- Replay date ---
        if hasattr(replay, "date") and replay.date:
            dt = replay.date
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            replay_time: str = dt.isoformat()
        else:
            replay_time = "1970-01-01T00:00:00+00:00"

        return {
            "error": None,
            "replay_hash": replay_hash,
            "replay_time": replay_time,
            # Team 1
            "team_1_player_1_name": t1p1.name,
            "team_1_player_2_name": t1p2.name,
            "team_1_player_1_race": t1p1_race,
            "team_1_player_2_race": t1p2_race,
            "team_1_player_1_handle": t1p1_handle,
            "team_1_player_2_handle": t1p2_handle,
            # Team 2
            "team_2_player_1_name": t2p1.name,
            "team_2_player_2_name": t2p2.name,
            "team_2_player_1_race": t2p1_race,
            "team_2_player_2_race": t2p2_race,
            "team_2_player_1_handle": t2p1_handle,
            "team_2_player_2_handle": t2p2_handle,
            # Result
            "result_int": result_int,
            "match_result": _RESULT_INT_TO_STR_2V2[result_int],
            # Shared
            "observers": observers,
            "map_name": replay.map_name,
            "game_duration_seconds": duration,
            "game_privacy": replay.attributes[16]["Game Privacy"],
            "game_speed": replay.attributes[16]["Game Speed"],
            "game_duration_setting": replay.attributes[16]["Game Duration"],
            "locked_alliances": replay.attributes[16]["Locked Alliances"],
            "cache_handles": cache_handles,
        }

    except Exception as exc:
        return {"error": f"sc2reader failed: {type(exc).__name__}: {exc}"}

    finally:
        sys.stderr = original_stderr
        devnull.close()
