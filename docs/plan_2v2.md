# 2v2 Implementation Plan

## Overview

2v2 is a parallel gamemode alongside 1v1. All 1v1 infrastructure is preserved
untouched. The 2v2 path adds:

- A party system (pre-match team formation)
- A 2v2 queue (individual players queuing, paired at wave time)
- A 2v2 matchmaking algorithm (teams vs teams)
- Four new DB tables (`matches_2v2`, `mmrs_2v2`, `preferences_2v2`, `replays_2v2`)
- A new `in_party` player status
- Parallel bot commands and backend endpoints

The guiding principle mirrors 1v1: the 2v2 matchmaker is a **stateless pure
function** over a queue list, all mutations go through `TransitionManager`, and
all real-time signals go through the existing WebSocket.

---

## 1. Schema Changes

### 1a. Existing table: `players`

Add `'in_party'` to the `player_status` CHECK constraint:

```sql
CHECK (player_status IN
    ('idle', 'queueing', 'in_match', 'timed_out', 'in_party')
)
```

When a player accepts a party invite:
- `player_status = 'in_party'`
- `current_match_mode = '2v2'`
- `current_match_id = NULL`

When a player leaves a party or the party is disbanded:
- `player_status = 'idle'`
- `current_match_mode = NULL`

When a party queues (both members run `/queue 2v2`):
- `player_status = 'queueing'` (same as 1v1; `in_party` is not a queueing state)
- `current_match_mode = '2v2'`

`/admin statusreset` clears `in_party` → `idle` automatically because it
already calls `_set_player_status(uid, "idle", match_mode=None, match_id=None)`.
The transition also needs to purge the player from the in-memory `parties_2v2`
dict (see §3).

The existing `reset_all_player_statuses()` at backend startup resets every
player to `idle` unconditionally; the `parties_2v2` dict is already empty
after a restart, so no extra work is needed there.

---

### 1b. New table: `mmrs_2v2`

MMR is per **unique player pair**, not per race. There is no `race` column.

```sql
CREATE TABLE IF NOT EXISTS mmrs_2v2 (
    id                      BIGSERIAL PRIMARY KEY,
    player_1_discord_uid    BIGINT NOT NULL,   -- smaller of the two UIDs (normalized)
    player_2_discord_uid    BIGINT NOT NULL,   -- larger of the two UIDs (normalized)
    player_1_name           TEXT NOT NULL,
    player_2_name           TEXT NOT NULL,
    mmr                     SMALLINT NOT NULL,
    games_played            INTEGER NOT NULL DEFAULT 0,
    games_won               INTEGER NOT NULL DEFAULT 0,
    games_lost              INTEGER NOT NULL DEFAULT 0,
    games_drawn             INTEGER NOT NULL DEFAULT 0,
    last_played_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (player_1_discord_uid, player_2_discord_uid)
);
```

UIDs are stored in ascending order (smaller first) so that the pair
`(A, B)` and `(B, A)` always resolve to the same row. The lookup key is
always `(min(uid_1, uid_2), max(uid_1, uid_2))`.

ELO is calculated at the team level using the pair MMR directly. Both players
on the team win or lose the same amount together — there are no individual
per-race 2v2 ratings.

---

### 1c. New table: `matches_2v2`

Four players: Team 1 (players 1 & 2) vs Team 2 (players 3 & 4).
Races are recorded as played (assigned at match creation, confirmed/corrected
by replay). One report per team.

```sql
CREATE TABLE IF NOT EXISTS matches_2v2 (
    id                          BIGSERIAL PRIMARY KEY,

    -- Team 1
    team_1_player_1_uid         BIGINT NOT NULL,
    team_1_player_2_uid         BIGINT NOT NULL,
    team_1_player_1_name        TEXT NOT NULL,
    team_1_player_2_name        TEXT NOT NULL,
    team_1_player_1_race        TEXT NOT NULL
        CHECK (team_1_player_1_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    team_1_player_2_race        TEXT NOT NULL
        CHECK (team_1_player_2_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    team_1_mmr                  SMALLINT NOT NULL,   -- pair MMR at match time

    -- Team 2
    team_2_player_1_uid         BIGINT NOT NULL,
    team_2_player_2_uid         BIGINT NOT NULL,
    team_2_player_1_name        TEXT NOT NULL,
    team_2_player_2_name        TEXT NOT NULL,
    team_2_player_1_race        TEXT NOT NULL
        CHECK (team_2_player_1_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    team_2_player_2_race        TEXT NOT NULL
        CHECK (team_2_player_2_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    team_2_mmr                  SMALLINT NOT NULL,

    -- Reporting (one per team; either member may submit)
    team_1_reporter_uid         BIGINT,
    team_1_report               TEXT
        CHECK (team_1_report IN (
            'team_1_win', 'team_2_win', 'draw',
            'abort', 'abandoned', 'invalidated', 'no_report'
        )),
    team_2_reporter_uid         BIGINT,
    team_2_report               TEXT
        CHECK (team_2_report IN (
            'team_1_win', 'team_2_win', 'draw',
            'abort', 'abandoned', 'invalidated', 'no_report'
        )),

    -- Resolution
    match_result                TEXT
        CHECK (match_result IN (
            'team_1_win', 'team_2_win', 'draw', 'conflict',
            'abort', 'abandoned', 'invalidated', 'no_report'
        )),
    team_1_mmr_change           SMALLINT,
    team_2_mmr_change           SMALLINT,

    -- Map / server
    map_name                    TEXT NOT NULL,
    server_name                 TEXT NOT NULL,

    -- Timestamps
    assigned_at                 TIMESTAMPTZ,
    completed_at                TIMESTAMPTZ,

    -- Admin
    admin_intervened            BOOLEAN NOT NULL DEFAULT FALSE,
    admin_discord_uid           BIGINT DEFAULT NULL,

    -- Replays (one upload slot per team)
    team_1_replay_path          TEXT,
    team_1_replay_row_id        BIGINT,
    team_1_uploaded_at          TIMESTAMPTZ,
    team_2_replay_path          TEXT,
    team_2_replay_row_id        BIGINT,
    team_2_uploaded_at          TIMESTAMPTZ
);
```

**Reporting rule:** Either member of a team may call `PUT
/matches_2v2/{match_id}/report`. The endpoint checks that the submitter is
on the relevant team, that no report has already been submitted for that
team, and records `team_N_reporter_uid` + `team_N_report`. Once both teams
have reported, the match resolves normally (or marks conflict).

---

### 1d. New table: `preferences_2v2`

Identical shape to `preferences_1v1`. Stores the last race/veto choices for
the `/queue 2v2` pre-fill, keyed per individual player.

```sql
CREATE TABLE IF NOT EXISTS preferences_2v2 (
    id                  BIGSERIAL PRIMARY KEY,
    discord_uid         BIGINT NOT NULL UNIQUE,
    last_chosen_races   TEXT[],
    last_chosen_vetoes  TEXT[]
);
```

---

### 1e. New table: `replays_2v2`

Same shape as `replays_1v1` extended to four players.

```sql
CREATE TABLE IF NOT EXISTS replays_2v2 (
    id                          BIGSERIAL PRIMARY KEY,
    matches_2v2_id              BIGINT NOT NULL,
    replay_path                 TEXT NOT NULL UNIQUE,
    replay_hash                 TEXT NOT NULL,
    replay_time                 TIMESTAMPTZ NOT NULL,
    uploaded_at                 TIMESTAMPTZ NOT NULL,
    -- Four players (team_1_p1, team_1_p2, team_2_p1, team_2_p2)
    team_1_player_1_name        TEXT NOT NULL,
    team_1_player_2_name        TEXT NOT NULL,
    team_2_player_1_name        TEXT NOT NULL,
    team_2_player_2_name        TEXT NOT NULL,
    team_1_player_1_race        TEXT NOT NULL
        CHECK (team_1_player_1_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    team_1_player_2_race        TEXT NOT NULL
        CHECK (team_1_player_2_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    team_2_player_1_race        TEXT NOT NULL
        CHECK (team_2_player_1_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    team_2_player_2_race        TEXT NOT NULL
        CHECK (team_2_player_2_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    match_result                TEXT NOT NULL
        CHECK (match_result IN ('team_1_win', 'team_2_win', 'draw')),
    -- sc2reader handles (all four players pooled)
    team_1_player_1_handle      TEXT NOT NULL,
    team_1_player_2_handle      TEXT NOT NULL,
    team_2_player_1_handle      TEXT NOT NULL,
    team_2_player_2_handle      TEXT NOT NULL,
    observers                   TEXT[] NOT NULL DEFAULT '{}',
    map_name                    TEXT NOT NULL,
    game_duration_seconds       INTEGER NOT NULL,
    game_privacy                TEXT NOT NULL,
    game_speed                  TEXT NOT NULL,
    game_duration_setting       TEXT NOT NULL,
    locked_alliances            TEXT NOT NULL,
    cache_handles               TEXT[] NOT NULL,
    upload_status               TEXT NOT NULL
        CHECK (upload_status IN ('pending', 'completed', 'failed'))
);
```

---

## 2. Polars Schemas and Row Types (`backend/domain_types/dataframes.py`)

Add schemas and TypedDicts for all four new tables, following the exact same
pattern as the existing `_1v1` variants.

New schema constants: `MATCHES_2V2_SCHEMA`, `MMRS_2V2_SCHEMA`,
`PREFERENCES_2V2_SCHEMA`, `REPLAYS_2V2_SCHEMA`.

Add all four to `TABLE_SCHEMAS` so `DatabaseReader.load_all_tables()` picks
them up automatically.

New TypedDicts: `Matches2v2Row`, `MMRs2v2Row`, `Preferences2v2Row`,
`Replays2v2Row`. Also update `PlayersRow.player_status` type annotation to
make it clear `'in_party'` is now a valid value (it's still `str`, so no
change in practice — just document it).

---

## 3. In-Memory State (`backend/orchestrator/state.py`)

### New DataFrames

```python
self.matches_2v2_df: pl.DataFrame = pl.DataFrame()
self.mmrs_2v2_df: pl.DataFrame = pl.DataFrame()
self.preferences_2v2_df: pl.DataFrame = pl.DataFrame()
self.replays_2v2_df: pl.DataFrame = pl.DataFrame()
```

These are populated at startup the same way as the 1v1 DataFrames (via
`_populate_postgres_data()`, which iterates `TABLE_SCHEMAS` automatically
once the schemas are added).

### New Ephemeral Collections

```python
self.queue_2v2: list[QueueEntry2v2] = []
self.parties_2v2: dict[int, PartyEntry2v2] = {}   # keyed by leader_uid
```

`parties_2v2` is a plain dict; scanning it is O(n) over the number of active
parties which will be small. `reset_all_player_statuses()` does NOT need to
touch this dict because it is already empty after a restart. However,
`reset_player_status` (the admin single-player reset) DOES need to scan and
purge the affected player from `parties_2v2` (see §6c).

---

## 4. Ephemeral Types (`backend/domain_types/ephemeral.py`)

### `PartyEntry2v2`

```python
class PartyEntry2v2(TypedDict):
    leader_uid: int
    leader_name: str
    member_uid: int
    member_name: str
    created_at: datetime
```

Stored in `StateManager.parties_2v2` keyed by `leader_uid`. The member can
look up their party by scanning values for `member_uid`. (Party size is always
exactly 2; no need for a list.)

### `QueueEntry2v2`

Individual queue entry — one per player, not per team.

```python
class QueueEntry2v2(TypedDict):
    discord_uid: int
    player_name: str
    party_partner_uid: int   # the other party member's UID
    bw_race: str | None
    sc2_race: str | None
    map_vetoes: list[str]
    joined_at: datetime
    wait_cycles: int
```

`party_partner_uid` is included directly so the matchmaker can pair entries
as a pure function without needing access to `parties_2v2`.

### `QueueEntry2v2Team`

Formed at wave time by the matchmaker from two paired `QueueEntry2v2` objects.
Internal to the matchmaker; never stored.

```python
class QueueEntry2v2Team(TypedDict):
    player_1_uid: int
    player_2_uid: int
    player_1_name: str
    player_2_name: str
    player_1_bw_race: str | None
    player_1_sc2_race: str | None
    player_2_bw_race: str | None
    player_2_sc2_race: str | None
    team_mmr: int
    map_vetoes: list[str]   # union of both players' vetoes
    joined_at: datetime     # earlier of the two join timestamps
    wait_cycles: int        # max of the two wait_cycles values
```

### `MatchCandidate2v2`

Output of the 2v2 matchmaker. Includes **assigned races** for each player
(determined during pool assignment; see §7).

```python
class MatchCandidate2v2(TypedDict):
    team_1_player_1_uid: int
    team_1_player_2_uid: int
    team_1_player_1_name: str
    team_1_player_2_name: str
    team_1_player_1_race: str   # specific race assigned for this match
    team_1_player_2_race: str
    team_1_mmr: int
    team_1_map_vetoes: list[str]
    team_2_player_1_uid: int
    team_2_player_2_uid: int
    team_2_player_1_name: str
    team_2_player_2_name: str
    team_2_player_1_race: str
    team_2_player_2_race: str
    team_2_mmr: int
    team_2_map_vetoes: list[str]
```

### `MatchParams2v2`

Same shape as `MatchParams1v1` — map, server, channel. The 2v2 map pool
uses the same `maps.json` structure (or a 2v2-specific season key if
introduced later).

---

## 5. Party System

### 5a. Party Lifecycle

```
[both idle]
    │
    ├─ Leader runs /party @member ──→ pending invite stored in-memory
    │                                  member receives DM with Accept/Decline
    │
    ├─ Member accepts ──→ both: player_status='in_party', current_match_mode='2v2'
    │                           PartyEntry2v2 added to StateManager.parties_2v2
    │
    ├─ Member declines ──→ pending invite removed; no status change
    │
    ├─ [party formed; both in_party]
    │
    ├─ Each player independently runs /queue 2v2
    │    └─ player_status='queueing', added to queue_2v2
    │
    ├─ [matchmaking wave fires; both present → team formed → match found]
    │    └─ both: player_status='in_match'
    │
    ├─ [match completes] ──→ both: player_status='in_party' (back to party, not idle)
    │                              party persists for the next queue
    │
    └─ Leader or member runs /party leave ──→ both: player_status='idle'
                                                   party removed from dict
```

After a match completes, both players return to `in_party` (not `idle`), so
they can immediately re-queue without re-forming the party.

### 5b. Pending Invites

Pending invites are also ephemeral in-memory. `StateManager` gets:

```python
self.pending_party_invites_2v2: dict[int, PendingPartyInvite2v2] = {}
# keyed by invitee_uid
```

```python
class PendingPartyInvite2v2(TypedDict):
    inviter_uid: int
    inviter_name: str
    invitee_uid: int
    invitee_name: str
    invited_at: datetime
```

Only one pending invite per invitee at a time. A new invite from a different
leader overwrites the old one (the old invite button simply stops working since
the accept endpoint checks that the invite is still current).

Invites do **not** expire automatically (keep it simple). If either player
changes status before accepting, the accept endpoint rejects it.

### 5c. Party Guards

- `/party @user`: inviter must be `idle` or `in_party` as leader with no
  current member yet (re-invite on empty party). Invitee must be `idle`.
  Inviting someone who is `in_party`, `queueing`, or `in_match` is rejected
  with a clear error message. These checks happen on the backend endpoint, not
  just on the bot side, so they are enforced even if the bot is misbehaving.
- Accepting an invite: invitee must still be `idle`. Inviter must still be
  `idle` (they cannot have queued or joined another party in the meantime).
- `/party leave`: works from `in_party` status. Also works from `queueing`
  status — leaving the party while in queue auto-leaves the queue first,
  returns both players to `idle`.

### 5d. Bot Commands (`/party`)

New command group registered in `bot/commands/user/party_command.py`:

**`/party @user`**
- Checks: `check_if_dm`, `check_if_banned`, `check_if_completed_setup`,
  `check_if_accepted_tos`
- Calls `PUT /party_2v2/invite` on the backend
- On success: sends an invite DM to the target with an embed showing the
  inviter's name and an Accept / Decline button view
- Accept button → `PUT /party_2v2/respond` with `accepted=true`
- Decline button → `PUT /party_2v2/respond` with `accepted=false`

**`/party leave`**
- No special pre-checks beyond basic ones
- Calls `DELETE /party_2v2/leave`
- Notifies both players via DM on success

**`/party status`**
- Calls `GET /party_2v2/{discord_uid}`
- Returns an embed showing current party state (or "You are not in a party")

### 5e. New Bot Check: `check_if_not_in_party`

Used as a guard on `/party @user` to prevent sending invites while already
fully-partied. Reads `player_status` from `GET /players/{uid}`.

### 5f. Backend Endpoints (party)

- `PUT /party_2v2/invite` — validate, create pending invite, return invite
  details for the bot to relay to the invitee via DM
- `PUT /party_2v2/respond` — accept/decline; on accept, set both players to
  `in_party` and add `PartyEntry2v2` to state
- `DELETE /party_2v2/leave` — remove player from party; if leader leaves,
  disband; if member leaves, leader returns to idle; both players get status
  reset
- `GET /party_2v2/{discord_uid}` — return party info for this player (or null)

### 5g. Backend Transitions (`_party.py` — new module)

New module `backend/orchestrator/transitions/_party.py` with:
- `create_party_invite(self, inviter_uid, inviter_name, invitee_uid, invitee_name)`
- `respond_to_party_invite(self, invitee_uid, accepted)`
- `leave_party(self, discord_uid)` — handles both leader and member leaving,
  returns both UIDs so the orchestrator/bot can notify them

Bound into `TransitionManager.__init__.py` alongside the other modules.

### 5h. Interaction with `/admin statusreset`

`reset_player_status` in `_admin.py` (called by `/admin statusreset`) should
also call `leave_party` logic for the target player — or at minimum, scan and
remove the player from `parties_2v2` and reset their party partner's status
to `idle` if their partner is now partnerless. The cleanest approach: after
`_set_player_status(uid, "idle", ...)`, call a `_purge_party_membership(uid)`
helper that removes the player from any party and resets the remaining party
member to `idle` (without the full `leave_party` event flow, since this is
an admin action).

---

## 6. Queue System

### 6a. `/queue` Command Changes

The existing `/queue` command is renamed internally to be explicitly 1v1.
A `game_mode` optional parameter is added:

```
/queue [game_mode: 1v1 | 2v2]   (default: 1v1)
```

When `game_mode=2v2`:
1. Check `check_if_in_party` (new check — player must have `player_status='in_party'`)
2. Load saved `preferences_2v2` from `GET /preferences_2v2/{uid}`
3. Show race/veto setup view (same UI as 1v1, just different endpoint target)
4. On confirm → `POST /queue_2v2/join`
5. Player status becomes `queueing`, `current_match_mode='2v2'`

### 6b. New Bot Check: `check_if_in_party`

```python
async def check_if_in_party(interaction) -> bool:
    # GET /players/{uid}, check player_status == 'in_party'
    # Raises NotInPartyError if not
```

This is **only** used as a guard for `/queue game_mode=2v2`.

### 6c. Backend: `join_queue_2v2` / `leave_queue_2v2`

New functions in `_queue.py` (or a separate `_queue_2v2.py`):

`join_queue_2v2`:
- Player must be `in_party` to join (not `idle`, not `queueing`)
- Look up party to get `party_partner_uid`
- Look up or create `mmrs_2v2` row for this pair (using normalized UID pair)
- Build `QueueEntry2v2` and append to `state_manager.queue_2v2`
- Set `player_status = 'queueing'`, `current_match_mode = '2v2'`

`leave_queue_2v2`:
- Remove from `queue_2v2`
- Set `player_status = 'in_party'` (back to party, not idle — the party
  remains; only the queue entry is removed)

### 6d. Backend Endpoints (queue)

- `POST /queue_2v2/join`
- `DELETE /queue_2v2/leave`
- `GET /queue_2v2/stats` — breakdown similar to 1v1 (bw_bw, sc2_sc2, mixed
  team counts)

---

## 7. Matchmaking Algorithm (`backend/algorithms/matchmaker_2v2.py`)

New file, same stateless pure-function design as `matchmaker.py`.

Entry point: `run_matchmaking_wave_2v2(queue: list[QueueEntry2v2]) -> tuple[list[QueueEntry2v2], list[MatchCandidate2v2]]`

### 7a. Step 1 — Form Teams

Group `queue` by `party_partner_uid` pairs. A team is valid only when both
members are present. Unpaired entries (partner not yet in queue) are returned
as remaining with incremented `wait_cycles`.

```
for each entry in queue:
    if partner is also in queue → form QueueEntry2v2Team
    else → remains in queue (wait_cycles += 1)
```

`QueueEntry2v2Team` fields:
- `team_mmr`: looked up from `mmrs_2v2` for this pair (default MMR if no
  record exists)
- `map_vetoes`: union of both players' vetoes
- `wait_cycles`: `max(p1.wait_cycles, p2.wait_cycles)`
- `joined_at`: `min(p1.joined_at, p2.joined_at)`
- Race fields: preserved as-is from each player's queue entry (resolved in
  the next step)

### 7b. Step 2 — Categorise Teams into Pools

A team's **possible compositions** are determined by what each member queued:

| Player 1 \ Player 2 | bw_only | sc2_only | both |
|---|---|---|---|
| **bw_only** | BW+BW only | BW + SC2 only | BW+BW or BW + SC2 |
| **sc2_only** | BW + SC2 only | SC2+SC2 only | SC2+SC2 or BW + SC2 |
| **both** | BW+BW or BW + SC2 | SC2+SC2 or BW + SC2 | BW+BW, SC2+SC2, or BW + SC2 |

Three pools: `pure_bw`, `pure_sc2`, `mixed`.

- A team is **eligible for `pure_bw`** if both players have a `bw_race`.
- A team is **eligible for `pure_sc2`** if both players have a `sc2_race`.
- A team is **eligible for `mixed`** if at least one player has `bw_race` and
  at least one has `sc2_race` (the two players need not be the same ones
  covering both sides; e.g., P1=BW only + P2=SC2 only qualifies as BW + SC2-only).

A team that qualifies for multiple pools (flexible) is distributed using the
same equalise logic as the 1v1 matchmaker (balance pool sizes first, then
skill). This is applied independently between the `pure_bw`/`pure_sc2` pair
and the `mixed` pool is separate.

Valid matches:
- `pure_bw` team vs `pure_sc2` team
- `mixed` team vs `mixed` team

### 7c. Step 3 — Race Assignment

When a team is assigned to a pool, the specific race for each player is pinned:

- **`pure_bw` pool**: each player plays their `bw_race`.
- **`pure_sc2` pool**: each player plays their `sc2_race`.
- **`mixed` pool**: one player plays BW, the other plays SC2.
  - If only one player has `bw_race` → that player plays BW.
  - If only one player has `sc2_race` → that player plays SC2.
  - If both have both → P1 plays BW, P2 plays SC2 (deterministic; players
    can coordinate privately beforehand or swap in-game).

### 7d. Step 4 — Build Candidates and Match

Same MMR window and scoring formula as 1v1 but using `team_mmr`:

```
max_diff    = BASE_MMR_WINDOW + wait_cycles * MMR_WINDOW_GROWTH_PER_CYCLE
wait_factor = max(team_1.wait_cycles, team_2.wait_cycles)
score       = mmr_diff² − 2^wait_factor × WAIT_PRIORITY_COEFFICIENT
```

The Hungarian algorithm is reused as-is (it operates on a cost matrix, agnostic
to what the rows/columns represent).

### 7e. Step 5 — Map Selection (Veto Counting)

In 2v2, up to four players can each veto maps, potentially exhausting the
entire pool. The 1v1 `_available_maps` approach (eliminate vetoed maps, pick
randomly from remainder) breaks down.

New function `_available_maps_2v2`:
- Count how many of the four players vetoed each map.
- Find the minimum veto count across all maps.
- Pick randomly from maps at the minimum count.

This guarantees a map is always selected regardless of how many vetoes are
submitted. Maps with 0 vetoes are always preferred; in the extreme case where
every map is vetoed, the least-vetoed map(s) are used.

Server resolution uses `get_best_server_for_teams(team_1_regions, team_2_regions)`
from `common/lookups/cross_table_lookups.py`, passing all four players'
`location` fields as two lists. See §12b for the full algorithm.

---

## 8. Match Lifecycle (2v2)

### 8a. Match Creation

`run_matchmaking_wave` in `_match.py` gets a `run_matchmaking_wave_2v2` sibling
that:
1. Calls `matchmaker_2v2.run_matchmaking_wave_2v2(queue_2v2)`
2. For each `MatchCandidate2v2`:
   - Looks up `mmrs_2v2` row IDs for both pairs
   - Calls `resolve_match_params_2v2` (map + server)
   - Inserts a `matches_2v2` row
   - Sets all four players to `in_match`
3. Returns created match rows (for WS broadcast)

### 8b. Confirmation

Same flow as 1v1 (`confirm_match_2v2`). Any of the four players can confirm.
"Both confirmed" means at least one player per team has confirmed (2 of 4), OR
all four have confirmed — TBD on exact rule. Simplest: require one confirmation
per team (party leader or any member).

60-second confirmation timeout applies. On abandonment, all four players return
to `in_party` status (not idle — the parties persist).

### 8c. Reporting

`PUT /matches_2v2/{match_id}/report`

Any player on a team may call this endpoint to submit that team's report. The
endpoint:
1. Identifies which team the caller is on.
2. Checks that no report has been submitted for that team yet.
3. Records `team_N_reporter_uid` and `team_N_report`.
4. If both teams have now reported: resolve if they agree; mark conflict if not.

On resolution (either agreed result or conflict), all four players return to
`in_party`.

### 8d. MMR Updates

ELO is calculated at team level using the pair's `mmrs_2v2.mmr` as the
effective rating. Both players' names in the `mmrs_2v2` row are updated if
they have changed. The `mmrs_2v2` row for each team is updated in-place
(games_played, games_won/lost/drawn, mmr, last_played_at).

### 8e. Replay Upload

Same DM-based flow as 1v1. Either team member can upload. The upload is
associated with their team's replay slot. `sc2reader` handles 2v2 replays
natively (it parses all players present). The verifier needs to check four
players instead of two, but the core parsing is unchanged.

### 8f. WebSocket Events

All six existing event types are reused. The payload includes `"game_mode":
"2v2"` so the bot's WS listener can route to the right handler. No new event
type names are needed.

New WS events needed for party:
- `party_invite_accepted` — both members notified when party forms (so the
  bot can send a confirmation DM to the leader)

---

## 9. Admin Changes

### 9a. `/admin snapshot game_mode=2v2`

New endpoint `GET /admin/snapshot_2v2` returns:
- `parties`: list of all active `PartyEntry2v2` objects (not yet queueing,
  just formed)
- `queue`: `queue_2v2` entries grouped by party
- `active_matches`: all 2v2 matches with `match_result IS NULL`
- `dataframe_stats`: row counts for the four 2v2 DataFrames

The snapshot command already has the `game_mode` parameter and the
`UnsupportedGameModeEmbed` fallback — just wire up the 2v2 case.

### 9b. `/admin statusreset` (unchanged interface, extended behavior)

No interface change. The backend `reset_player_status` transition is modified
to also call `_purge_party_membership(discord_uid)`, which:
- Removes the player from `parties_2v2` (whether leader or member)
- If the partner is still `in_party`, resets the partner to `idle` and clears
  their `current_match_mode`
- Removes both players' pending invite entries if any

---

## 10. Files Created

| File | Purpose |
|---|---|
| `backend/algorithms/matchmaker_2v2.py` | Stateless 2v2 matchmaking |
| `backend/algorithms/match_params_2v2.py` | Map veto counting + server resolution |
| `backend/orchestrator/transitions/_party.py` | Party lifecycle transitions |
| `backend/orchestrator/transitions/_queue_2v2.py` | 2v2 queue join/leave |
| `backend/orchestrator/transitions/_match_2v2.py` | 2v2 match wave, confirm, report, resolve |
| `backend/orchestrator/transitions/_mmr_2v2.py` | 2v2 MMR helpers |
| `backend/orchestrator/transitions/_replay_2v2.py` | 2v2 replay insert/update |
| `bot/commands/user/party_command.py` | `/party` command group |

## 11. Files Modified

| File | Change |
|---|---|
| `backend/database/schema.sql` | `in_party` status; 4 new tables |
| `backend/domain_types/dataframes.py` | 4 new schemas + row types |
| `backend/domain_types/ephemeral.py` | New ephemeral types |
| `backend/orchestrator/state.py` | New DFs + ephemeral collections |
| `backend/orchestrator/transitions/__init__.py` | Bind new module methods |
| `backend/orchestrator/orchestrator.py` | Expose new public methods |
| `backend/orchestrator/transitions/_admin.py` | `reset_player_status` purges party |
| `backend/orchestrator/transitions/_player.py` | `reset_all_player_statuses` comment on parties |
| `backend/api/endpoints.py` | New party + queue + match 2v2 endpoints |
| `backend/api/app.py` | Add `_matchmaker_loop_2v2` task |
| `bot/commands/user/queue_command.py` | Add `game_mode` parameter |
| `bot/helpers/checks.py` | `check_if_in_party`, `check_if_not_in_party` |
| `bot/core/app.py` | Register party command |
| `bot/core/ws_listener.py` | Route 2v2 match events |

---

## 12. Hard Problems

### 12a. Replay Player Identification

In 1v1, player identity in the replay is solved by race: the match is always
BW vs SC2, so the race uniquely identifies each player's slot. The verifier
does a simple set equality check and the parser assigns player_1/player_2 by
index.

In 2v2 this breaks in two distinct ways, and they interact.

**What sc2reader gives us for a 2v2 replay:**
Each of the 4 players has: `name` (in-game display name), `play_race`,
`team_id` (1 or 2), `is_observer`. Toon handles are extracted separately
via `_find_toon_handles(replay.raw_data)` by position. The parser currently
hard-rejects replays where `len(replay.players) != 2` — this guard must be
changed to accept 4 for 2v2.

**Problem A: Mapping replay teams to match teams**

The replay's team 1 and team 2 (from `team_id`) do not necessarily correspond
to match team 1 and team 2. Players may join the lobby in any order. You
need to determine which replay team is match team 1 and which is match team 2
before you can read a result.

For **BW+BW vs SC2+SC2**: the two replay teams have different race prefixes
(one is all bw_*, the other is all sc2_*). Team mapping is unambiguous without
name matching.

For **BW + SC2 vs BW + SC2**: both replay teams contain one bw_*
and one sc2_* player. Race alone cannot distinguish them. You need to match at
least one known player to their replay entry to determine team mapping.

**Problem B: Within-team player identity**

Once you know which replay team maps to which match team, you need to identify
which player within the team is team_N_player_1 vs team_N_player_2. This
matters for the `replays_2v2` record (which handle belongs to which slot).

For **BW+BW**: if the two BW players chose different specific races (e.g.
bw_terran + bw_zerg), identity is unambiguous. If both chose the same specific
race (e.g. both bw_terran), it is not — this is the genuinely hard sub-case.

For **SC2+SC2**: same logic.

For **BW + SC2 teams**: one player is BW, one is SC2 — race prefix disambiguates
within the team cleanly.

**Available matching signals (ranked by reliability):**

1. **Race (specific, not just prefix)**: Works when no two players on the same
   team chose the same specific race. Covers the majority of cases.

2. **Toon handle**: sc2reader extracts `toon_handle` strings (format
   `"1-S2-1-3456789"`) — a unique SC2 profile ID. If stored against a player's
   profile, exact matching is possible. Currently not stored at setup time.
   Could be progressively accumulated from replays after first match.

3. **Soft name matching**: sc2reader's `player.name` is the in-game display
   name. The `battletag` field in the player profile is `"Name#1234"`;
   stripping the `#suffix` and normalizing case gives a reasonable match
   signal. `alt_player_names` and `player_name` also apply. False negatives
   occur when the player changed their BattleTag display name or uses an alt
   account.

4. **LLM name matching**: Send the 4 expected names (player_name, battletag
   display) and the 4 replay names to a Claude API call and ask it to produce
   a mapping. Handles unicode, abbreviations, and name variations. Adds
   latency (~1s) and API cost per upload, but is a strong fallback when soft
   matching is ambiguous.

**Practical approach:**

Verification results should carry a confidence level:
- **Race-identified**: team mapping and within-team identity resolved purely by
  race. Auto-resolution safe.
- **Name-matched**: team mapping resolved via soft name matching. Report
  confidence alongside verification result; allow auto-resolution but flag it.
- **Ambiguous**: team mapping could not be determined. Do not auto-resolve;
  fall back to manual reporting.

For the initial implementation, target at minimum:
- Race identification (covers BW+BW vs SC2+SC2 fully, and within-team identity
  in most BW + SC2 cases)
- Soft name matching as fallback for team mapping in BW + SC2 vs BW + SC2
- Graceful degradation to manual reporting when both fail

The LLM approach and toon handle accumulation are deferred improvements.

**Note:** The `replays_2v2` row records handles by position. When within-team
identity is ambiguous (same specific race on both players), the handle
assignment is best-effort. This is acceptable — the record is for auditing,
not for enforcing match results.

---

### 12b. Server Selection for 4 Players

**Status: data complete, algorithm decided, implementation pending.**

The current 1v1 server selection is a symmetric lookup:
`cross_table["mappings"][region_A][region_B] → server`. It encodes an
implicit judgment about which server is "best" for each pair of geographic
regions, including institutional SC2 community knowledge about fairness. This
works cleanly for 2 players; it does not generalise to 4 because the
combinatorial space (16⁴ tuples) is infeasible to curate manually.

**The ping table (complete):**

Ping data lives as a top-level `"pings"` key inside the existing
`data/core/cross_table.json` — not a separate file. The `CrossTableData`
TypedDict (`common/json_types.py`) already includes:

```python
class CrossTableData(TypedDict):
    region_order: list[str]
    mappings: dict[str, dict[str, str]]
    pings: dict[str, dict[str, list[int] | None]]
```

Each entry is `[min_ms, max_ms]` or `null`. Using a range rather than a single
value captures the geographic spread within a region (e.g. NAW spans Hawaii to
eastern Montana). `null` means "unreachable or so poor it should never be
actively chosen" — it does not hard-exclude the server at algorithm time.
Instead, `null` entries are converted to `PING_INF = 9999`, ensuring the
algorithm always produces a result.

The scalar used for scoring is the **upper bound** (worst case, `val[1]`), not
the midpoint. This is appropriate for competitive fairness: you want the
worst-case latency to be acceptable, not just the average.

Notable null entries reflecting real-world routing limitations:
- All European regions (`EUW`, `EUE`): null for `KOR`, `TWN`, `SNG`, `AUS`
- `KRJ`: null for `EUC` (Japan pulls the upper bound above the usable range;
  a Korea-only split may revisit this)
- `USB`, `FER`: null for `USC`, `USE` (240-260ms, effectively unusable)
- `CHN`: null for `USC`, `USE`, `EUC`
- `THM`, `OCE`, `SEA`: null for `EUC`

All 16 geographic regions × 9 game servers are populated. The data is
"good enough" — the SC2 population is heavily concentrated in eastern coastal
China, Japan/Korea, and Europe/NA where routing is well understood.

**Lookup functions (complete):**

`common/lookups/cross_table_lookups.py` already provides:

```python
PING_INF: int = 9999

def get_ping_range(region: str, server: str) -> list[int] | None: ...
def get_ping_scalar(region: str, server: str) -> int:  # upper bound or PING_INF
def get_best_server_for_regions(regions: list[str]) -> str:  # pure minimisation (N players same team)
def get_best_server_for_teams(team_1_regions: list[str], team_2_regions: list[str]) -> str:
```

**The scoring algorithm (minimax):**

`get_best_server_for_teams` uses the following objective:

```
p(R, S)    = get_ping_scalar(R, S)   # upper bound, or PING_INF for null
t1_avg(S)  = mean(p(R, S) for R in team_1_regions)
t2_avg(S)  = mean(p(R, S) for R in team_2_regions)
score(S)   = max(t1_avg(S), t2_avg(S))
tiebreak   = t1_avg(S) + t2_avg(S)   # lower total wins ties
```

Pick the server minimising `score`, breaking ties by `tiebreak`.

**Why minimax over the earlier balanced formula:**

An earlier candidate formula was `(t1_avg + t2_avg)/2 + |t1_avg - t2_avg|`,
which penalises team imbalance with a 1:1 weight against average latency.
That formula was rejected because it sometimes picks a server where one team
plays at high latency in order to reduce the gap — e.g. routing NAW+NAW vs
THM+THM to KOR (190ms worst team) rather than USW (160ms worst team), because
USW has a 100ms gap and KOR only a 60ms gap. Minimax simply asks "what is the
worst-team experience?" and picks the server that minimises it, breaking ties
by total ping. This better matches competitive fairness intuition: nobody
should be forced to high latency just to "equalise suffering."

In practice the two formulas agree on ~88% of Tier 1+2 matchups. The 12%
that differ are cases where minimax is clearly more intuitive.

**Key structural findings from analysis:**

These findings informed the ping table and are useful context for understanding
2v2 server selection behaviour. Player tier estimates (by population):
- **Tier 1**: NAW, NAC, NAE, EUW, EUE, KRJ
- **Tier 2**: CHN, THM, USB
- **Tier 2.5**: FER, OCE
- **Tier 3**: CAM, SAM, SEA
- **Tier 4**: AFR, MEA (essentially no playerbase)

Key findings:
- **T1-only ceiling is 170ms** (EUW/EUE vs KRJ). The Korea-Europe divide is
  unavoidable and exists in 1v1 too. The algorithm routes these to USW or EUC
  depending on team composition, both equally bad.
- **USB as a teammate is not the problem; USB as a team composition is.**
  Pure USB+USB vs any T1 team routes to EUC or KOR at ~120ms — perfectly
  acceptable. The problem is USB paired with a European player (EUE+USB,
  EUW+USB), which has no viable server against Asian opponents (210-250ms).
  These team compositions are geographically incoherent.
- **KRJ is the best cross-Pacific ally.** Any team containing KRJ routes
  Asian T2 opponents (CHN, THM) to KOR at 100-110ms. KRJ+NA teams are
  especially effective. In a hypothetical where KRJ gains EUC access (~160ms
  via routing improvements), 82 additional matchups improve, with
  KRJ+EU vs USB opponents dropping from 250ms to 120ms.
- **CHN+USB is the hardest T2 team** for European T1 players to face
  (USW at 205ms). NA-heavy T1 teams can escape to KOR at 170-190ms instead.
- **EUE is the worst European partner for Asian T2 players** because EUE has
  null entries for KOR/TWN/SNG. CHN+EUE and THM+EUE are capped at USW:170ms
  against any T1 opponent, regardless of the NA players' regions.
- **The EUE→Asian server problem is confirmed geography, not a data gap.**
  A Croatian contact confirmed 250+ms to KOR/TWN/SNG. European access to Asian
  servers without specialized VPN infrastructure is not viable. The nulls
  in the ping table for EUW/EUE→KOR/TWN/SNG are correct.

**Implementation note:**

`get_best_server_for_teams` takes region lists (strings), not player objects.
The caller in `match_params_2v2.py` is responsible for extracting the four
players' `location` fields and passing them as two lists. A player with no
`location` set should fall back to a default region or be excluded from the
calculation (TBD at implementation time).

---

## 13. Open Questions / Future Considerations

- **Confirmation rule**: One per team (either member) or all four? One per team
  is simpler.
- **2v2 map pool**: `maps.json` already has a `"2v2"` top-level key with the
  same season-key structure as `"1v1"`. `match_params_2v2.py` accesses
  `maps["2v2"][season]` directly. **Also a latent bug to fix in 1v1**: the
  existing `_available_maps` in `match_params.py` iterates `maps.values()`
  (all game modes) rather than `maps["1v1"]` — harmless now because 2v2/FFA
  entries are empty stubs, but will silently corrupt the 1v1 map pool once
  2v2 maps are added. Fix `_available_maps` to scope to `maps["1v1"]` as part
  of this work.
- **Server resolution for 2v2**: Implemented via `get_best_server_for_teams`
  in `common/lookups/cross_table_lookups.py` using the minimax algorithm
  described in §12b. No fallback needed — the ping table is complete.
- **`/admin setmmr` for 2v2**: Would need to target a pair, not an individual.
  Defer until needed.
- **Leaderboard for 2v2**: `leaderboard_2v2` is stubbed in `StateManager`.
  Defer, same as 1v1 was deferred initially.
- **`/profile` 2v2 stats**: Could show pair-level MMR history. Defer.

## 14. Final Notes

Concrete gaps in the current type definitions:                                                           
                                                                                                           
  QueueEntry2v2 and MatchCandidate2v2 are both missing a location field for each player. The matchmaker is 
  supposed to be a pure function, but match_params_2v2.py needs the four players' regions to call          
  get_best_server_for_teams. In 1v1, the queue entry presumably carries location so the matchmaker can     
  build MatchCandidate1v1 with the region pair. The 2v2 types need the same — either location on         
  QueueEntry2v2 (one per player, pulled at queue join time) or both on QueueEntry2v2Team. Without this, the
   pure-function design breaks or you have to pass the players DataFrame into match creation.

  Related: QueueEntry2v2 doesn't have team_mmr. The plan says "looked up from mmrs_2v2" when forming teams 
  during the wave, but that requires the matchmaker to either receive the DataFrame as an argument or call
  a lookup function — both violate the pure-function design. Cleanest solution: look up (or create) the    
  mmrs_2v2 row at /queue_2v2/join time and store team_mmr directly in QueueEntry2v2, same as 1v1 does.   

  Still-unresolved design decisions:                                                                       
  
  Confirmation rule is still TBD ("one per team" vs "all four"). Pick one — it affects the WS handler, the 
  match embed, and the timeout behavior. One-per-team is simpler and mirrors the 1v1 spirit.             
                                                                                                           
  The /queue command change (adding a game_mode parameter to the existing command) may cause a Discord     
  slash command sync issue — Discord caches command trees and adding parameters to existing commands can be
   finicky. Consider whether /queue with a game_mode param is actually cleaner than just /queue2v2 as a    
  separate top-level command that requires party status.                                                 

  Things that might surprise you in sc2reader:                                                             
  
  The verifier currently hard-checks len(replay.players) != 2. Before you explore, know that in SC: Evo    
  2v2, sc2reader may list observers differently — some replays include referees or custom observers that 
  inflate the player count. The 1v1 verifier probably handles this with the observers field, but for 2v2   
  you'll want to confirm what replay.players actually contains vs replay.observers. Similarly, team_id on
  players should give you 1 or 2, but confirm whether sc2reader assigns these correctly for custom lobbies
  vs standard matchmaking.

  The BW + SC2 composition is worth probing specifically. In a BW + SC2 2v2 where two players use BW races
   and two use SC2 races, confirm that player.play_race gives you the specific race (e.g. "Terran" for BW
  Terran) or whether it gives you a generic indicator. The verifier needs to map this back to your internal
   bw_terran/sc2_terran distinction — how does sc2reader represent the race for a BW player in an SC: Evo
  game? Is it by handle prefix? This is the core thing to answer before writing any verification logic.

  Angles you might not have considered:

  Default MMR seeding for new pairs. Right now a fresh pair starts at 1500 regardless of individual 1v1    
  skill. An experienced 1v1 player teaming with another experienced player will get matched against
  genuinely new players for their first few 2v2 games. Could seed new pair MMR as (p1_1v1_mmr + p2_1v1_mmr)
   / 2 if both have played 1v1. Completely optional and deferrable, but costs almost nothing to implement
  at queue join time since you're already looking up the MMR row.

  The 1v1 map pool bug (_available_maps iterates all game modes) is a latent bomb. The moment you add real 
  maps to maps["2v2"], 1v1 matches start pulling from the 2v2 pool silently. Fix it alongside this work,
  not after.                                                                                               
                                                                                                         
  Party invite staleness: the plan says invites don't expire, and the accept endpoint rejects stale ones.  
  That's fine for the happy path, but if a player receives an invite DM and then the bot restarts, the
  in-memory invite is gone but the DM's Accept button still exists. The button press hits a dead endpoint. 
  Make sure the accept endpoint returns a clean "invite no longer valid" response rather than a 500, and
  the bot handles that gracefully.

---

## Replay Parser & Verifier

### sc2reader 2v2 Structure (confirmed from sample replay)

Key differences from 1v1:

| Attribute | 1v1 | 2v2 |
|---|---|---|
| `replay.players` | 2 Player objects, one per player | 4 Player objects; each has a `.pid` attribute (1-indexed player number, i.e. 1–4) |
| `replay.teams` | not used | list of 2 Team objects; `teams[0]` = Team 1, `teams[1]` = Team 2; each has a `.players` list of 2 Player objects |
| `replay.winner` | Player object or None | **Team object** with `.number` (1 or 2), or None for a draw; no string-parsing needed |
| `replay.game_type` | `"1v1"` | `"2v2"` |
| Toon handles | 2, one per player | 4, one per player, in ascending player-number (pid) order: handles[0] = Player 1, handles[1] = Player 2, handles[2] = Player 3, handles[3] = Player 4 |

**Critical:** Team composition is NOT always Players 1+2 vs Players 3+4. For example, Team 1 may consist of Players 1 and 4, and Team 2 of Players 2 and 3. Always use `replay.teams[N].players` to find team membership; never assume that player-number order maps to team order.

All other fields are structurally identical to 1v1: `cache_handles`, `observers`, `game_length`, `game_events` (for `PlayerLeaveEvent` duration), `date`, `map_name`, and `attributes[16]` game settings.

### Private Helper Reusability

All three private helpers in `replay_parser.py` are reusable as-is:

- `_fix_race()` — call once per player (4 times total)
- `_find_toon_handles()` — returns 4 handles for 2v2; ordering is player-number (pid) order, not team order
- `_extract_cache_handles()` — raw_data structure is identical

### Changes Required

#### `backend/algorithms/replay_parser.py`

1. **Rename** `parse_replay` → `parse_replay_1v1`. Update its docstring to say "1v1 only". Update its player-count guard comment accordingly.

2. **Add** `_RESULT_INT_TO_STR_2V2: dict[int, str] = {0: "draw", 1: "team_1_win", 2: "team_2_win"}`.

3. **Add** `parse_replay_2v2(replay_bytes: bytes) -> dict[str, Any]`:

   **Guards:**
   - `replay.game_type != "2v2"` → return error
   - `len(replay.players) != 4` → return error
   - `len(replay.teams) != 2` → return error

   **Team/player extraction:**
   Use `replay.teams[0].players` and `replay.teams[1].players` exclusively — never index into `replay.players` directly by position for team assignment. Each player object exposes `.pid` (1-indexed), `.name`, and `.play_race`.

   **Toon handle mapping:**
   Because handles are in pid order but team composition is arbitrary, build a pid-to-handle mapping before assigning handles to team slots:
   ```python
   all_handles = _find_toon_handles(replay.raw_data)
   # all_handles[i] belongs to the player with pid == i + 1
   # Require exactly 4 handles
   pid_to_handle = {p.pid: all_handles[p.pid - 1] for p in replay.players}
   # Then look up by each team member's pid:
   team_1_player_1_handle = pid_to_handle.get(team1_players[0].pid, "")
   # etc.
   ```

   **Winner:**
   - `replay.winner` is a Team object with `.number` (1 or 2) when a winner exists.
   - If `replay.winner is None`: `result_int = 0` (draw).
   - If `replay.winner.number == 1`: `result_int = 1`.
   - If `replay.winner.number == 2`: `result_int = 2`.
   - The 1v1 "was defeated!" message fallback does not apply to 2v2.
   - **TODO:** Stub a `_infer_winner_2v2(replay)` function that mirrors `_infer_winner_from_defeat` logic adapted for teams, for the case where `replay.winner is None`. For now the stub returns `None` unconditionally and the result falls through to draw. Add a `# TODO: implement team-level defeat inference` comment.

   **Duration:** Identical to 1v1 (first `PlayerLeaveEvent`, fallback to `game_length.seconds`).

   **Return dict** — keys exactly match `replays_2v2` column names (team-namespaced):
   ```python
   {
       "error": None,
       "replay_hash": ...,
       "replay_time": ...,
       "team_1_player_1_name": ..., "team_1_player_1_race": ..., "team_1_player_1_handle": ...,
       "team_1_player_2_name": ..., "team_1_player_2_race": ..., "team_1_player_2_handle": ...,
       "team_2_player_1_name": ..., "team_2_player_1_race": ..., "team_2_player_1_handle": ...,
       "team_2_player_2_name": ..., "team_2_player_2_race": ..., "team_2_player_2_handle": ...,
       "result_int": ...,         # 0=draw, 1=team_1_win, 2=team_2_win
       "match_result": ...,       # "draw" | "team_1_win" | "team_2_win"
       "observers": [...],
       "map_name": ...,
       "game_duration_seconds": ...,
       "game_privacy": ...,
       "game_speed": ...,
       "game_duration_setting": ...,
       "locked_alliances": ...,
       "cache_handles": [...],
   }
   ```

#### `backend/algorithms/replay_verifier.py`

Add `verify_replay_2v2(parsed, match, mods, maps) -> dict[str, Any]`:

The `match` argument is a `Matches2v2Row` dict.

**Races — set comparison, not ordered comparison:**
Each team has two races assigned in the match row; the replay also provides two races per team. The check is whether the *set* of races matches, not whether any specific player on the team has any specific race. This means:
- Team 1 check: `{match["team_1_player_1_race"], match["team_1_player_2_race"]}` == `{parsed["team_1_player_1_race"], parsed["team_1_player_2_race"]}`
- Team 2 check: same pattern with `team_2_*` fields
- These are two independent `"success": bool` entries in the result dict (`races_team_1`, `races_team_2`).

**Mirror match detection:**
A mirror match occurs when both teams have the *same* race composition (e.g. both teams are `{bw_terran, sc2_zerg}`). In this case, even if the race checks pass, it is ambiguous which team in the replay corresponds to which team in the match record — player display names are not fully reliable identifiers.

When a mirror is detected, the verifier sets a top-level `"mirror_match": True` flag in the result dict. The autoreporting logic (in the endpoint / transition) must treat this as a failure condition and fall back to manual reporting rather than auto-resolving the match result. The parse result itself is still returned; only autoreporting is blocked.

Add a stub helper `_resolve_mirror_match_names(parsed, match, players_df) -> dict[str, Any] | None` in `replay_verifier.py`:
- Takes the four player names from `parsed` and cross-references them against the `player_name` column of the players DataFrame (passed in from state) to attempt to identify which in-game team corresponds to which match team.
- Returns a resolution dict if the names unambiguously resolve, `None` otherwise.
- For now the stub always returns `None` (i.e. always falls back to manual) with a `# TODO: implement name-based mirror match resolution` comment.
- The mirror detection itself is cheap (set comparison of both teams' race sets) and always runs; the stub is only called when a mirror is detected.

**Map, mod, timestamp, game settings:** Copy existing 1v1 logic unchanged.

**AI players:** Check all 4 player name fields (`team_1_player_1_name`, `team_1_player_2_name`, `team_2_player_1_name`, `team_2_player_2_name`).

**Observers:** Same as 1v1 (0 expected).

#### `backend/api/endpoints.py`

- Update import: `parse_replay` → `parse_replay_1v1`
- Update the `run_in_executor` call to use `parse_replay_1v1`
- (The 2v2 replay endpoint `POST /matches_2v2/{match_id}/replay` is a separate addition that mirrors the 1v1 endpoint, dispatching `parse_replay_2v2` via the same `ProcessPoolExecutor`.)

---

## 15. Leader-Picks-All Queue Model

**Decision (2026-03-21):** The 2v2 queue uses a **leader-picks-all** design. Only the
party leader runs `/queue 2v2`. The leader selects all race preferences for the full
team at queue time. The non-leader member's status changes to `queueing` automatically
when the leader queues, and back to `in_party` when the leader leaves the queue or is
removed from it. The member cannot independently queue or leave the queue.

### 15a. Why Leader-Picks-All

Allowing each player to queue individually (the prior design) fails to express the
rich intra-team race coordination that 2v2 requires. In particular:

- Valid match types are **only** BW+BW vs SC2+SC2, or BW + SC2 vs BW + SC2. This is a
  team-level constraint that cannot be cleanly expressed by two independent per-player
  `bw_race / sc2_race` choices without a coordination protocol.
- In BW + SC2 compositions, teams care strongly about *which player* is BW and *which* is
  SC2 (BW Terran + SC2 Protoss is a very different comp from BW Protoss + SC2 Terran).
  Individual menus do not allow teams to express this preference reliably.
- Double same-race teams are legitimate (e.g. BW Terran + BW Terran). The UI must
  support this explicitly.

Leader-picks-all solves all three problems in a single interaction with a clear author
of the choice.

### 15b. Queue Setup UI (`QueueSetupEmbed2v2` / `QueueSetupView2v2`)

**Three optional team compositions** — leader may leave any blank, must fill at least one:

| Menu | Leader race | Member race |
|---|---|---|
| **Pure BW** | BW race for leader (bw_T, bw_Z, bw_P, or same as member) | BW race for member |
| **Mixed** | BW or SC2 race for leader | Opposite era race for member |
| **Pure SC2** | SC2 race for leader (sc2_T, sc2_Z, sc2_P, or same as member) | SC2 race for member |

Each comp is two linked `discord.ui.Select` menus (one per player). Dropdowns are
**order-aware**: they clearly label which choice is for the leader and which is for the
partner, showing both player names.

**Double same-race is valid.** The Pure BW and Pure SC2 menus must therefore include
all possible pairings including (bw_Terran, bw_Terran), (sc2_Zerg, sc2_Zerg), etc.
Since these are two selects per comp (one per player), this is naturally supported —
both selects include all three races in their era independently.

**Mixed validation** (enforced by the backend at join time, not the UI):
- The combined pair must cover different eras: one BW race + one SC2 race.
- The leader's and member's mixed choices must not both be BW or both be SC2.

### 15c. `QueueEntry2v2` Redesigned Shape

One entry per **party** (keyed by leader's discord_uid), not per player.

```python
class QueueEntry2v2(TypedDict):
    discord_uid: int                 # leader's discord_uid
    player_name: str                 # leader's display name
    party_member_discord_uid: int    # member's discord_uid
    party_member_name: str           # member's display name
    # Optional team compositions (at least one must be non-None)
    pure_bw_leader_race: str | None  # leader's BW race (e.g. "bw_terran")
    pure_bw_member_race: str | None  # member's BW race
    mixed_leader_race: str | None    # leader's race in mixed comp (BW or SC2)
    mixed_member_race: str | None    # member's race in mixed comp (opposite era)
    pure_sc2_leader_race: str | None # leader's SC2 race
    pure_sc2_member_race: str | None # member's SC2 race
    nationality: str                 # leader's ISO country code
    location: str | None             # leader's geographic region
    member_nationality: str          # member's ISO country code
    member_location: str | None      # member's geographic region
    team_mmr: int                    # from mmrs_2v2, looked up at join time
    team_letter_rank: str            # from leaderboard_2v2; "U" if unranked
    map_vetoes: list[str]            # leader's vetoes (member has no separate veto)
    joined_at: datetime
    wait_cycles: int
```

`QueueEntry2v2Team` is **no longer needed** — the entry already represents the full
team. The matchmaker operates on `list[QueueEntry2v2]` directly, where each entry is
already a complete team.

### 15d. `join_queue_2v2` Transition Changes

```
Input: leader discord_uid, discord_username, 6 optional race fields, map_vetoes
Guards:
  - leader must have player_status == "in_party"
  - leader must be the party leader (not the member) — check parties_2v2[leader_uid]
  - at least one comp must be non-None
  - if BW + SC2 comp is set: mixed_leader_race and mixed_member_race must cover different eras
On success:
  - Look up or create mmrs_2v2 row for (leader, member) pair
  - Look up member's nationality + location from players_df
  - Append one QueueEntry2v2 to state_manager.queue_2v2
  - Set leader player_status = "queueing"
  - Set member player_status = "queueing"  ← NEW (both players change status)
```

### 15e. `leave_queue_2v2` Transition Changes

```
Input: discord_uid (must be the leader)
Guards: leader must be in queue_2v2
On success:
  - Remove the QueueEntry2v2 from queue_2v2
  - Set leader player_status = "in_party"
  - Set member player_status = "in_party"  ← both revert
```

If a member tries to call leave_queue_2v2, it is rejected ("Only the party leader can
leave the 2v2 queue.").

### 15f. Match Confirmation (Leader-on-behalf-of-team)

The party leader confirms the match for their entire team. A non-leader `in_match`
player cannot confirm. After both teams confirm:
- All four players receive `MatchInfoEmbed2v2` via DM.
- Leader and member both become `in_match` at match creation (not at confirmation).

The WS `match_found` event payload includes all four player discord_uids so the bot can
DM each player's confirmation request to the **leaders** only, and the info embed to
**all four** after `both_confirmed`.

### 15g. `/queue_2v2/join` Request Model

```python
class Queue2v2JoinRequest(BaseModel):
    discord_uid: int            # leader only
    discord_username: str
    pure_bw_leader_race: str | None = None
    pure_bw_member_race: str | None = None
    mixed_leader_race: str | None = None
    mixed_member_race: str | None = None
    pure_sc2_leader_race: str | None = None
    pure_sc2_member_race: str | None = None
    map_vetoes: list[str] = []
```

---

## 16. Bot Component Renames (1v1-Specific Suffixes)

The following bot components are currently named generically but will need 2v2
equivalents. To avoid ambiguity, they must be renamed with a `1v1` suffix before 2v2
versions are added.

### Components to Rename

| Current name | New name | File |
|---|---|---|
| `MatchInfoEmbed` | `MatchInfoEmbed1v1` | `bot/components/embeds.py:413` |
| `QueueSetupEmbed` | `QueueSetupEmbed1v1` | `bot/components/embeds.py:210` |
| `QueueSetupView` | `QueueSetupView1v1` | `bot/components/views.py:1736` |
| `MatchFoundView` | `MatchFoundView1v1` | `bot/components/views.py:1976` |
| `MatchReportView` | `MatchReportView1v1` | `bot/components/views.py:2007` |

### Files That Reference These Components

**`MatchInfoEmbed`** (→ `MatchInfoEmbed1v1`):
- `bot/core/ws_listener.py`
- `bot/helpers/replay_handler.py`
- `bot/components/views.py` (internal reference from `MatchFoundView`)
- `bot/core/bootstrap.py`
- `bot/core/message_queue.py`

**`QueueSetupEmbed`** (→ `QueueSetupEmbed1v1`):
- `bot/components/views.py` (internal reference from `QueueSetupView`)
- `bot/commands/user/queue_command.py`

**`QueueSetupView`** (→ `QueueSetupView1v1`):
- `bot/components/views.py` (self-reference / internal)
- `bot/commands/user/queue_command.py`

**`MatchFoundView`** (→ `MatchFoundView1v1`):
- `bot/core/ws_listener.py`
- `bot/commands/user/queue_command.py`

**`MatchReportView`** (→ `MatchReportView1v1`):
- `bot/core/ws_listener.py`
- `bot/helpers/replay_handler.py`
- `bot/components/views.py` (internal reference)
- `bot/commands/user/queue_command.py`

### New 2v2 Components to Add

After renaming, create parallel 2v2 versions:

| New component | File |
|---|---|
| `MatchInfoEmbed2v2` | `bot/components/embeds.py` |
| `QueueSetupEmbed2v2` | `bot/components/embeds.py` |
| `QueueSetupView2v2` | `bot/components/views.py` |
| `MatchFoundView2v2` | `bot/components/views.py` |
| `MatchReportView2v2` | `bot/components/views.py` |

---

## 17. Compatibility Audit: Everything Implemented vs. Leader-Picks-All

Scope: everything implemented or designed so far, assessed against the leader-picks-all
queue model decided in §15.

### ✅ Fully Compatible — No Changes Required

**`PendingPartyInvite2v2` (ephemeral type)**
Nothing race-specific. The invite only carries player identity. Compatible.

**`PartyEntry2v2` (ephemeral type)**
Distinguishes `leader_discord_uid` from `member_discord_uid` — exactly the field
leader-picks-all needs to enforce who can queue. Compatible.

**`_party.py` transitions (`create_party_invite`, `respond_to_party_invite`,
`leave_party`, `get_party`, `purge_party_membership`)**
Party lifecycle has no interaction with race selection. `leave_party` already resets
both players' statuses, which is the right behavior when the party is disbanded while
the leader is queueing (leave_party → purge from queue → both back to idle).
Compatible.

**Party backend endpoints and bot `party_command.py`**
No race information flows through the party system. Compatible.

**`_handle_missing_mmr_2v2` in `_queue.py`**
Looks up or creates the pair MMR row at queue join time. Unaffected by UI model.
Compatible.

**`add_mmr_2v2` in `database.py`**
Unaffected. Compatible.

**`MatchCandidate2v2` (ephemeral type)**
The final shape — four players with explicitly assigned races — is correct for
leader-picks-all. The matchmaker produces this from the team compositions declared by
each party's leader. No change to the type definition needed.

**`MatchParams2v2` (ephemeral type)**
Map + server + channel. Unaffected. Compatible.

**Schema tables (`matches_2v2`, `mmrs_2v2`, `replays_2v2`)**
None of these store queue-time race preferences. They store the races *as played* (set
at match creation from the chosen comp). Compatible.

**`admin statusreset` calling `_purge_party_membership`**
The admin helper purges the player from the party dict and resets the partner. Under
leader-picks-all, this also needs to purge the leader's queue entry (removing both
players from the queue). `_purge_party_membership` already calls `_remove_from_queue_2v2`
which removes all entries where the uid matches — but under the new model there is only
one entry per party (the leader's), keyed by the leader's uid. If the admin is resetting
the **member** (not the leader), `_remove_from_queue_2v2` currently filters on
`discord_uid` which is the leader's uid in the entry. A member reset would not find
and remove that entry. **This is a latent bug once the new model is implemented.**
Fix: `_remove_from_queue_2v2` should also check `party_member_discord_uid`.

**`replay_parser.py` 2v2 implementation (`_infer_winner_2v2`, `indeterminate`)**
Operates on sc2reader structures, not queue race data. Fully compatible.

**`replay_verifier.py` (`verify_replay_2v2`, `indeterminate` flag)**
Verifies races, map, settings. Race verification compares sets — compatible with any
race assignment strategy used by the matchmaker. Compatible.

**Schema `replays_2v2.match_result` CHECK with `'indeterminate'`**
Unaffected. Compatible.

---

### ❌ Incompatible — Must Be Changed

**`QueueEntry2v2` (ephemeral type)**
Currently has `bw_race: str | None` and `sc2_race: str | None` — one per player, one
entry per player. Needs complete redesign to the shape in §15c: one entry per party,
six optional race fields, member identity fields, member location/nationality.

**`QueueEntry2v2Team` (ephemeral type)**
No longer needed. Under leader-picks-all, each `QueueEntry2v2` already represents the
full team — the matchmaker does not need to pair two separate entries. Remove or
replace with a note that `QueueEntry2v2` IS the team unit.

**`join_queue_2v2` transition in `_queue.py`**
Currently takes `bw_race` + `sc2_race` for a single player and sets only that player
to `queueing`. Needs to:
- Accept the 6 race fields from §15c instead.
- Enforce that the caller is the party leader (not just any `in_party` player).
- Look up member's nationality + location from `players_df`.
- Set **both** leader and member to `queueing`.
- Validate the BW + SC2 comp covers both eras.

**`leave_queue_2v2` transition in `_queue.py`**
Currently removes an entry by matching `discord_uid` on the entry's `discord_uid`
field (which will now always be the leader's uid). A member calling this endpoint would
find nothing and return "Player is not in the 2v2 queue." That is the correct behavior,
but the error message should be changed to "Only the party leader can leave the 2v2
queue." Additionally, `leave_queue_2v2` must set **both** leader and member back to
`in_party`, not just the caller.

**`Queue2v2JoinRequest` model in `models.py`**
Currently:
```python
class Queue2v2JoinRequest(BaseModel):
    discord_uid: int
    discord_username: str
    bw_race: str | None = None
    sc2_race: str | None = None
    map_vetoes: list[str] = []
```
Replace with the shape in §15g (6 race fields).

**`POST /queue_2v2/join` endpoint in `endpoints.py`**
Must pass the new 6-field race structure to the transition.

**Plan §5a (party lifecycle flow)**
The step "Each player independently runs `/queue 2v2`" is wrong. Replace with:
"Party leader runs `/queue 2v2` → both players set to `queueing`."

**Plan §6 (Queue System section)**
The entire §6 queue description (§6a–§6d) was written for the individual-queue model.
The redesign in §15 supersedes §6c–§6d. §6a's `game_mode` parameter question about
`/queue` vs `/queue2v2` as a separate command is still open.

**Plan §4 (`QueueEntry2v2` and `QueueEntry2v2Team` in the ephemeral types spec)**
Still describes old per-player shape. §15c supersedes.

**Plan §7 (Matchmaking Algorithm)**
§7a "Form Teams" step described pairing two separate queue entries into a
`QueueEntry2v2Team`. This step is eliminated — each `QueueEntry2v2` is already a team.
The matchmaker operates directly on the queue list, with each entry representing a
paired team ready to be matched against other teams. §7b pool categorization logic
changes: instead of looking at `player_1.bw_race` and `player_2.sc2_race` separately,
inspect the three optional comp fields on each entry:
- Entry is eligible for `pure_bw` pool if `pure_bw_leader_race is not None`.
- Entry is eligible for `pure_sc2` pool if `pure_sc2_leader_race is not None`.
- Entry is eligible for `mixed` pool if `mixed_leader_race is not None`.
An entry must declare at least one comp to be in the queue; the matchmaker distributes
multi-pool-eligible entries using the same equalization logic as 1v1.

§7c race assignment: the specific race is no longer resolved by the matchmaker from
ambiguous individual choices. It is directly read from the chosen comp:
- If assigned to `pure_bw` pool: `team_player_1_race = pure_bw_leader_race`,
  `team_player_2_race = pure_bw_member_race`.
- If assigned to `pure_sc2` pool: similarly from `pure_sc2_*` fields.
- If assigned to `mixed` pool: from `mixed_leader_race` / `mixed_member_race`.

---

### ⚠️ Not Yet Implemented — Design Has Drifted

**`preferences_2v2` schema (plan §1d)**
Planned as identical shape to `preferences_1v1` (per-player `last_chosen_races` text
array). Under leader-picks-all, the preferences are the 6 comp race fields + vetoes,
stored per leader. The schema should be redesigned as:

```sql
CREATE TABLE IF NOT EXISTS preferences_2v2 (
    id                       BIGSERIAL PRIMARY KEY,
    discord_uid              BIGINT NOT NULL UNIQUE,  -- leader's uid
    last_pure_bw_leader_race TEXT,
    last_pure_bw_member_race TEXT,
    last_mixed_leader_race   TEXT,
    last_mixed_member_race   TEXT,
    last_pure_sc2_leader_race TEXT,
    last_pure_sc2_member_race TEXT,
    last_chosen_vetoes       TEXT[]
);
```

This is a **schema change** — the `preferences_2v2` table has not been created in
production yet (it was defined in plan §1d but not yet migrated), so this is not a
breaking change.

**`QueueSetupEmbed` / `QueueSetupView` (bot UI)**
These currently implement the 1v1 queue UI. They need 2v2 variants with 3 optional
comp sections (BW + BW, BW + SC2, SC2 + SC2), each section showing two selects (leader
race, member race). Both player names must be visible in the embed so the leader knows
which select controls which player.

The 1v1 versions must be renamed (§16) before 2v2 variants are added.

**`MatchFoundView` / `MatchReportView` (bot UI)**
These will need 2v2 variants that are delivered to **all four** players but where the
confirm/report actions are constrained: confirm only available to leaders, report
available to any team member (one per team). The 1v1 versions must be renamed first.