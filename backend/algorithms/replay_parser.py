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

_RESULT_INT_TO_STR: dict[int, str] = {
    0: "draw",
    1: "player_1_win",
    2: "player_2_win",
}

# Hard-coded sc2reader race name → ladder race code mapping.
# Alias resolution via the races.json lookup is NOT done here because this
# function runs in a worker process that may not have the lookup modules
# initialised.  Unknown race names are returned as-is and normalised by the
# caller before inserting into the database.
_RACE_MAP: dict[str, str] = {
    "Terran": "sc2_terran",
    "Zerg": "sc2_zerg",
    "Protoss": "sc2_protoss",
    "BW Terran": "bw_terran",
    "BW Zerg": "bw_zerg",
    "BW Protoss": "bw_protoss",
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


def parse_replay(replay_bytes: bytes) -> dict[str, Any]:
    """
    Parse raw .SC2Replay bytes and return a dict with all fields needed for
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
            "match_result": _RESULT_INT_TO_STR[result_int],
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
