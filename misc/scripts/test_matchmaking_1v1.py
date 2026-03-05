#!/usr/bin/env python3
"""
Smoke-test for misc/dump/dump-1.py (stateless 1v1 matchmaking wave).

Run from the repository root:
    python misc/scripts/test_matchmaking_1v1.py

Covers:
  - BW-only players matched against each other via "both" pool redistribution
  - SC2-only players matched against each other via "both" pool redistribution
  - Mixed BW / SC2 / "both" queues
  - Players with no MMR (default-MMR fallback)
  - High wait_cycles widening the match window
  - Queue too small to produce matches (<2 players)
  - Multi-wave simulation: unmatched players accumulate wait_cycles
"""

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

# ---------------------------------------------------------------------------
# Load dump-1.py via importlib (hyphen in filename prevents normal import)
# ---------------------------------------------------------------------------

_DUMP1_PATH = REPO_ROOT / "misc" / "dump" / "dump-1.py"

_spec = importlib.util.spec_from_file_location("dump_1", _DUMP1_PATH)
assert _spec is not None and _spec.loader is not None, f"Could not load {_DUMP1_PATH}"
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

run_matchmaking_wave = _mod.run_matchmaking_wave

from backend.domain_types.state_types import MatchCandidate1v1, QueueEntry1v1  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)
_UID_COUNTER = iter(range(10_000, 99_999))


def make_entry(
    name: str,
    bw_race: str | None = None,
    sc2_race: str | None = None,
    bw_mmr: int | None = None,
    sc2_mmr: int | None = None,
    map_vetoes: List[str] | None = None,
    wait_cycles: int = 0,
) -> QueueEntry1v1:
    """Create a minimal QueueEntry1v1 for testing."""
    return QueueEntry1v1(
        discord_uid=next(_UID_COUNTER),
        player_name=name,
        bw_race=bw_race,
        sc2_race=sc2_race,
        bw_mmr=bw_mmr,
        sc2_mmr=sc2_mmr,
        map_vetoes=map_vetoes or [],
        joined_at=_NOW,
        wait_cycles=wait_cycles,
    )


def _fmt_match(m: MatchCandidate1v1) -> str:
    return (
        f"  {m['player_1_name']} ({m['player_1_race']}, {m['player_1_mmr']} MMR)"
        f"  vs  "
        f"{m['player_2_name']} ({m['player_2_race']}, {m['player_2_mmr']} MMR)"
        f"  |  diff={abs(m['player_1_mmr'] - m['player_2_mmr'])}"
    )


def run_scenario(title: str, queue: List[QueueEntry1v1]) -> None:
    """Run one matchmaking wave and print a formatted summary."""
    print(f"\n{'=' * 70}")
    print(f"SCENARIO: {title}")
    print(f"  Queue size: {len(queue)}")
    for e in queue:
        races = "/".join(filter(None, [
            f"BW:{e['bw_race']}({e['bw_mmr']})" if e["bw_race"] else None,
            f"SC2:{e['sc2_race']}({e['sc2_mmr']})" if e["sc2_race"] else None,
        ]))
        print(f"    {e['player_name']:15s}  {races}  wait={e['wait_cycles']}")

    remaining, matches = run_matchmaking_wave(queue)

    print(f"\n  Matches formed ({len(matches)}):")
    if matches:
        for m in matches:
            print(_fmt_match(m))
    else:
        print("  (none)")

    print(f"\n  Remaining in queue ({len(remaining)}):")
    if remaining:
        for r in remaining:
            print(f"    {r['player_name']:15s}  wait_cycles={r['wait_cycles']}")
    else:
        print("  (none)")
    print()


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def scenario_bw_only_even() -> None:
    """Four BW-only players with close MMRs."""
    queue = [
        make_entry("Alice",   bw_race="bw_terran", bw_mmr=1600),
        make_entry("Bob",     bw_race="bw_zerg", bw_mmr=1580),
        make_entry("Charlie", bw_race="bw_protoss", bw_mmr=1400),
        make_entry("Diana",   bw_race="bw_terran", bw_mmr=1420),
    ]
    run_scenario("BW-only players (4, even pool)", queue)


def scenario_sc2_only_even() -> None:
    """Four SC2-only players with close MMRs."""
    queue = [
        make_entry("Eve",     sc2_race="sc2_terran", sc2_mmr=2200),
        make_entry("Frank",   sc2_race="sc2_zerg", sc2_mmr=2180),
        make_entry("Grace",   sc2_race="sc2_protoss", sc2_mmr=2050),
        make_entry("Hank",    sc2_race="sc2_terran", sc2_mmr=2070),
    ]
    run_scenario("SC2-only players (4, even pool)", queue)


def scenario_mixed_bw_sc2_both() -> None:
    """Two BW-only, two SC2-only, two 'both' players."""
    queue = [
        make_entry("Iris",  bw_race="bw_terran",  bw_mmr=1500),
        make_entry("Jake",  bw_race="bw_zerg",  bw_mmr=1480),
        make_entry("Karen", sc2_race="sc2_protoss", sc2_mmr=1500),
        make_entry("Leo",   sc2_race="sc2_terran", sc2_mmr=1460),
        make_entry("Mia",   bw_race="bw_terran",  sc2_race="sc2_zerg", bw_mmr=1510, sc2_mmr=1490),
        make_entry("Ned",   bw_race="bw_zerg",  sc2_race="sc2_protoss", bw_mmr=1450, sc2_mmr=1470),
    ]
    run_scenario("Mixed BW / SC2 / both (6 players)", queue)


def scenario_no_mmr_defaults() -> None:
    """Players with None MMR – should use DEFAULT_MMR=1500 fallback."""
    queue = [
        make_entry("Oscar",  bw_race="bw_terran",  bw_mmr=None),
        make_entry("Penny",  sc2_race="sc2_zerg", sc2_mmr=None),
        make_entry("Quinn",  bw_race="bw_protoss",  bw_mmr=None),
        make_entry("Rachel", sc2_race="sc2_terran", sc2_mmr=None),
    ]
    run_scenario("No MMR (default fallback)", queue)


def scenario_wide_mmr_gap_low_wait() -> None:
    """Large MMR gap – should NOT match on first wave."""
    queue = [
        make_entry("Sam",  bw_race="bw_terran", bw_mmr=2000),
        make_entry("Tara", sc2_race="sc2_zerg", sc2_mmr=1200),
    ]
    run_scenario("Wide MMR gap, low wait_cycles (expect no match)", queue)


def scenario_wide_mmr_gap_high_wait() -> None:
    """Same large MMR gap but high wait_cycles widens the window."""
    queue = [
        make_entry("Sam",  bw_race="bw_terran",  bw_mmr=2000, wait_cycles=16),
        make_entry("Tara", sc2_race="sc2_zerg", sc2_mmr=1200, wait_cycles=16),
    ]
    run_scenario("Wide MMR gap, high wait_cycles (expect match)", queue)


def scenario_too_few_players() -> None:
    """Only one player – no matches possible; wait_cycles must increment."""
    queue = [
        make_entry("Uma", bw_race="bw_terran", bw_mmr=1500),
    ]
    run_scenario("Single player (no match)", queue)


def scenario_empty_queue() -> None:
    """Empty queue – should return empty lists without error."""
    run_scenario("Empty queue", [])


def scenario_multi_wave_simulation() -> None:
    """
    Two waves: one pair cannot match on wave 1 (gap too large) but can on wave 2
    after wait_cycles accumulate.
    """
    print(f"\n{'=' * 70}")
    print("SCENARIO: Multi-wave simulation (2 waves)")

    queue: List[QueueEntry1v1] = [
        make_entry("Victor", bw_race="bw_terran",  bw_mmr=1800),
        make_entry("Wendy",  sc2_race="sc2_zerg", sc2_mmr=1400),
    ]

    for wave in range(1, 4):
        remaining, matches = run_matchmaking_wave(queue)
        print(f"\n  Wave {wave}: queue={len(queue)}, matches={len(matches)}, remaining={len(remaining)}")
        for m in matches:
            print("   ", _fmt_match(m))
        for r in remaining:
            print(f"    Unmatched: {r['player_name']} wait_cycles={r['wait_cycles']}")
        queue = remaining
        if not queue:
            break

    print()


def scenario_many_players() -> None:
    """Larger queue with a mix of BW-only, SC2-only, and both."""
    bw_only = [
        make_entry(f"BW_{i}", bw_race="bw_terran", bw_mmr=1500 + i * 30)
        for i in range(5)
    ]
    sc2_only = [
        make_entry(f"SC2_{i}", sc2_race="sc2_zerg", sc2_mmr=1500 + i * 30)
        for i in range(5)
    ]
    both_players = [
        make_entry(f"Both_{i}", bw_race="bw_protoss", sc2_race="sc2_terran", bw_mmr=1500 + i * 20, sc2_mmr=1490 + i * 20)
        for i in range(4)
    ]
    run_scenario("Large mixed queue (14 players)", bw_only + sc2_only + both_players)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print("Running 1v1 matchmaking wave tests against misc/dump/dump-1.py")

    scenario_bw_only_even()
    scenario_sc2_only_even()
    scenario_mixed_bw_sc2_both()
    scenario_no_mmr_defaults()
    scenario_wide_mmr_gap_low_wait()
    scenario_wide_mmr_gap_high_wait()
    scenario_too_few_players()
    scenario_empty_queue()
    scenario_multi_wave_simulation()
    scenario_many_players()

    print(f"{'=' * 70}")
    print("All scenarios completed.")


if __name__ == "__main__":
    main()
