# Plan: Move beyond rigid wave-based 1v1 matchmaking

Captures the design discussion for the TODO entry:

> Migrate wave-based matchmaking approach to a non-wave-based
> algorithm/faster wave-based algorithm with no matching obligations per
> wave so we don't get synchronization issues causing players to match up
> into the same opponents over and over again.

## Current behavior (1v1)

Trigger: `backend/api/app.py` calls `run_matchmaking_wave_method` once
every 60 seconds, on the top of the minute. The full snapshot of
`queue_1v1` is processed together; a player who joins at 12:00:01 waits
the full 59 s for the next tick.

Per-wave pure function (`backend/algorithms/matchmaker.py`):

1. Deep-copy queue, increment `wait_cycles` for everyone.
2. Build two parallel lists:
   - `bw_rows` — every entry with a non-null `bw_race` (BW-only + Both).
   - `sc2_cols` — every entry with a non-null `sc2_race` (SC2-only + Both).
   A "Both" player exists in both lists.
3. Build a square `n × n` cost matrix
   (`n = max(len(bw_rows), len(sc2_cols))`) padded with `_SENTINEL`.
   - Self-match cells (same `discord_uid` on both axes) → `_SENTINEL`.
   - Pairs whose `|row.bw_mmr − col.sc2_mmr|` exceeds **both** players'
     MMR windows → `_SENTINEL`. Window =
     `BASE_MMR_WINDOW (100) + wait_cycles × MMR_WINDOW_GROWTH_PER_CYCLE (50)`.
   - Otherwise:
     `cost = diff² − 2^max(wait_a, wait_b) × WAIT_PRIORITY_COEFFICIENT (20)`.
4. O(n³) Hungarian → minimum-weight maximum-cardinality matching. Sentinel
   values guarantee Hungarian first maximises real matches, then
   minimises total score.
5. Side-commitment for Both players falls out of the assignment (row →
   BW, column → SC2).
6. Returns `(remaining_unmatched, candidates)`. The transition layer
   writes matches and replaces `state_manager.queue_1v1` with `remaining`.

## Two distinct problems

1. **Sync latency.** A player joining at 12:00:01 waits 59 s. With ≤ 4
   players online, every wave has the same input → Hungarian is
   deterministic → identical pairings repeat indefinitely.
2. **No history.** The cost function only knows MMR diff and wait
   cycles. There is no way to express "you two just played each other
   three times in a row, prefer the new guy even if his MMR is 80 off."

## Design

### Step 1 — Persistent recent-match memory

Add to `StateManager`:

```python
recent_opponents_1v1: dict[tuple[int, int], list[datetime]]
# key: canonical (min_uid, max_uid); value: timestamps of recent matches
```

- Populated at startup by `DatabaseReader` from `matches_1v1` (e.g. last
  24 h or last 10 per pair — bounded).
- Pruned by age on each read or via a periodic sweep.
- Updated in `TransitionManager._match.create_match` (writethrough order:
  Supabase first, then this dict).
- No new SQL — `matches_1v1` already has `created_at`.

### Step 2 — Rematch penalty in the cost function

```python
score = diff² − 2^wait_factor × WAIT_PRIORITY_COEFFICIENT + rematch_penalty
```

```python
recent = recent_opponents_1v1.get(canonical_pair, [])
fresh = [t for t in recent if (now - t) < REMATCH_DECAY_WINDOW]
penalty = REMATCH_BASE_PENALTY * sum(decay(now - t) for t in fresh)
```

Properties:

- The penalty must be **comparable to MMR² units** so it actually
  competes. Window-edge cost ≈ `100² = 10_000`. So a base of 5_000–15_000
  per recent match makes a single fresh rematch "worth" ~50–120 MMR of
  skill mismatch.
- Cap the total penalty at `BASE_MMR_WINDOW²` so a rematch is always
  strictly better than no match. Must never exceed `_SENTINEL`.

### Step 3 — Address sync (recommended: Option B)

**Option A — Faster waves.** Drop interval from 60 s to 5–10 s. Cheap,
but with deterministic Hungarian and no history, four idle players still
grind into the same pairings every tick. Doesn't fix the root cause.

**Option B — Shorter waves + new-player bias (recommended).**
1. Wave interval down to ~10–15 s (Hungarian over n ≤ 100 is sub-ms; the
   60 s is a legacy choice, not a perf constraint).
2. Newly-arrived players (`wait_cycles == 0`) get a small *negative*
   score bias against everyone — i.e. prefer pairing them over rematches.
3. Combined with step 2, the rematch penalty breaks deterministic loops:
   each match makes the next rematch costlier, so two players will
   eventually be allowed to rematch (penalty decays) but won't be forced
   to do so on every wave the moment they're the only feasible pair.

Pure, synchronous, no new infra outside `StateManager`. Smallest change
that dissolves both problems.

**Option C — Event-driven.** Trigger matchmaking on `queue_join` /
`queue_leave` with a ~500 ms debounce instead of a timer. The "real"
fix, but `wait_cycles` semantics change ("attempts seen" vs "minutes
waited"), so window growth has to be re-derived from `joined_at`.
Bigger refactor; do later if Option B isn't sufficient.

### Step 4 — Lone-pair safety valve

To handle "5–6 minutes waiting when they're the only two online":

- Track `consecutive_waves_with_no_match` per player or per canonical
  pair.
- After N consecutive waves where the only feasible opponent is someone
  recently played, **decay the rematch penalty to zero** for that pair.
- Guarantees liveness: only-two-online → rematch within ~N waves.
- With shorter waves, N ≈ 3–5 → 30–75 s before the rematch is forced.

### Step 5 — New tuning constants

```python
WAVE_INTERVAL_SECONDS: int = 15
REMATCH_DECAY_WINDOW_HOURS: int = 2
REMATCH_BASE_PENALTY: float = 8000.0   # ~ (90 MMR)²
REMATCH_MAX_PENALTY: float = 10000.0   # cap = BASE_MMR_WINDOW²
NEW_PLAYER_BONUS: float = 4000.0       # ~ (63 MMR)² head start
LONE_PAIR_LIVENESS_WAVES: int = 4
```

## Test surface

Matchmaker stays pure — it just takes two extra arguments
(`recent_opponents`, `now`). New invariants to cover:

- Two recently-matched players prefer a new third opponent if available.
- Two recently-matched players eventually re-match if they're the only
  ones in queue (liveness within N waves).
- Rematch penalty decays to zero after `REMATCH_DECAY_WINDOW_HOURS`.
- A 200-MMR-gap new opponent is preferred over a same-MMR fresh
  rematch; the same new opponent is **not** preferred at a 600-MMR gap.

## Recommended order of work

1. **Steps 1 + 2 + 4.** Persistent rematch memory + cost-function term +
   liveness valve. Highest value, lowest risk. Wave timing stays at 60 s.
   Ship and observe whether the sync problem still bites.
2. **Step 3-B.** Shorter wave interval + `NEW_PLAYER_BONUS`. Tiny diff
   once step 1 is in place.
3. Only if production still shows sync issues: **Step 3-C** (event-driven)
   as a separate larger refactor.
