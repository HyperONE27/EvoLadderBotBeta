# 2v2 Implementation Record

This document describes what was actually built across the 2v2 implementation sessions. It is a companion to `plan_2v2.md`, which describes the full design intent. Everything here is live in the codebase unless noted otherwise.

---

## 1. Schema & Polars Types

**What:** Four new DB tables (`matches_2v2`, `mmrs_2v2`, `preferences_2v2`, `replays_2v2`) with corresponding Polars `DataType` schemas in `TABLE_SCHEMAS` and TypedDict row types (`Matches2v2Row`, `MMRs2v2Row`, `Preferences2v2Row`, `Replays2v2Row`) in `backend/domain_types/dataframes.py`. The existing `players` table gains an `in_party` status (player is in a formed party, not yet queueing).

**Why:** All 1v1 infrastructure — the `StateManager`, `DatabaseReader`, `DatabaseWriter`, `TransitionManager` pattern — works by keying on table name strings against a registry of Polars schemas. Adding 2v2 tables to the registry is the minimum integration needed to load, validate, and write 2v2 data through the exact same machinery as 1v1.

---

## 2. Ephemeral Types

**What:** Six new in-memory TypedDicts in `backend/domain_types/ephemeral.py`:
- `PendingPartyInvite2v2` — an outstanding invite (inviter + invitee UIDs/names, timestamp)
- `PartyEntry2v2` — a formed party (leader + member, created_at)
- `QueueEntry2v2` — one queue slot per party; holds all three composition slots (pure BW, pure SC2, mixed) so the matchmaker can derive compatibility
- `MatchCandidate2v2` — output of the matchmaker; one match, fully resolved composition
- `MatchParams2v2` — map, server, channel for a specific 2v2 match
- `LeaderboardEntry2v2` — 2v2 leaderboard row (not yet populated)

`StateManager` gains three new live collections: `queue_2v2: list[QueueEntry2v2]`, `parties_2v2: dict[int, PartyEntry2v2]` (keyed by leader UID), and `pending_party_invites_2v2`.

**Why:** The 1v1 queue is a plain list of `QueueEntry1v1`; 2v2 follows the same pattern. Keeping party state in a dict (not a DB table) means zero latency for invite/accept/leave and no risk of stale DB reads during the sub-second confirmation window.

---

## 3. Party System

**What:** Full invite/accept/leave/disband lifecycle, backend and bot.

Backend:
- `Orchestrator.create_party_invite` — validates both players are idle, creates a `PendingPartyInvite2v2`
- `Orchestrator.respond_to_party_invite` — accept: promotes both players to `in_party` status and creates `PartyEntry2v2`; decline: clears the invite
- `Orchestrator.leave_party` — sets both players back to `idle`, removes the `PartyEntry2v2`
- `Orchestrator.get_party` — read-only lookup by any member UID

Endpoints: `PUT /party_2v2/invite`, `PUT /party_2v2/respond`, `DELETE /party_2v2/leave`, `GET /party_2v2/{discord_uid}`

Bot: `/party invite {user}`, `/party leave`, `/party status` slash commands (`bot/commands/user/party_command.py`).

**Why:** Party formation is synchronous request/response — the invitee accepts via the `/party respond` command, not via a WS event. This avoids a round-trip WS broadcast just to update a button state. The backend is the single source of truth for party state; the bot simply reads the response and sends a DM to the other player to notify them.

---

## 4. 2v2 Matchmaking Algorithm

**What:** `backend/algorithms/matchmaker_2v2.py` — stateless pure function `run_matchmaking_wave_2v2(queue)`.

Key design decisions:
- **Queue entries are per party, not per player.** Each `QueueEntry2v2` carries both players' names/UIDs and all composition preferences. The matchmaker never needs to look up a partner — it's already in the entry.
- **Compatibility check:** two parties are compatible if one can play BW while the other plays SC2 (in either order), or if both declared mixed. This mirrors the original plan's "find the match first, resolve composition afterward" principle.
- **Scoring:** `mmr_diff² − 2^wait_factor × WAIT_PRIORITY_COEFFICIENT` — identical formula to the 1v1 matchmaker, reusing the same config constants.
- **Pairing:** O(n³) Hungarian algorithm via `scipy.optimize.linear_sum_assignment`, same as 1v1.
- **Composition resolution:** After pairing, determine which team plays BW and which plays SC2. If both could swap (both declared BW and SC2), the assignment is randomised to prevent systematic advantage.

**Why:** Reusing the 1v1 scoring formula and Hungarian-algorithm pairing keeps the two matchmakers parallel and auditable. The key difference from 1v1 is the compatibility predicate (era-based, not race-based) and that the unit of matching is a pre-formed party, not an individual.

---

## 5. preferences_2v2 — Saved Race & Veto Preferences

**What:** Full stack from DB to REST:
- `backend/lookups/preferences_2v2_lookups.py` — `get_preferences_2v2_by_discord_uid`, registered in bootstrap
- `DatabaseWriter.upsert_preferences_2v2` — upserts to the `preferences_2v2` table
- `TransitionManager.upsert_preferences_2v2` — updates the in-memory Polars DataFrame and queues a DB write
- `Orchestrator.get_preferences_2v2` / `upsert_preferences_2v2` — public API
- Endpoints: `GET /preferences_2v2/{discord_uid}`, `PUT /preferences_2v2`

Preferences stored: last used leader/member races per composition type (pure BW, pure SC2, mixed) + last chosen map vetoes.

**Why:** Mirrors `preferences_1v1` exactly. Persisting race selections means the queue setup view can restore defaults across sessions, reducing friction for repeat queuers. The three-composition structure (pure BW, pure SC2, mixed) allows each composition's preferred races to be remembered independently.

---

## 6. Queue & Match Lifecycle Endpoints

**What:** Backend endpoints for the full 2v2 match lifecycle:
- `POST /queue_2v2/join` — party leader submits composition choices; both players set to `queueing`
- `DELETE /queue_2v2/leave` — either player can trigger; both removed from queue, returned to `in_party`
- `PUT /matches_2v2/{match_id}/confirm` — player confirms; when both players on a team confirm, the team is confirmed
- `PUT /matches_2v2/{match_id}/abort` — player aborts; broadcasts `match_aborted`
- `PUT /matches_2v2/{match_id}/report` — team reports result (`team_1_win`, `team_2_win`, `draw`); broadcasts `match_completed` or `match_conflict`

**Why:** Symmetric with 1v1 endpoints. All state mutations go through `TransitionManager`, all broadcasts go through the WebSocket — no direct state access from endpoint handlers.

---

## 7. WebSocket Game-Mode Routing

**What:** All 2v2 backend broadcasts inject `{"game_mode": "2v2", **dict(match)}` into the event payload. 1v1 broadcasts are unchanged (no `game_mode` field). The bot's `_handle_message` reads `data.get("game_mode", "1v1")` and dispatches to the appropriate handler set.

Six 2v2 handlers in `bot/core/ws_listener.py`:
- `_on_match_found_2v2` — sends `MatchFoundEmbed` + `MatchFoundView2v2` to all 4 players
- `_on_all_confirmed_2v2` — sends `MatchInfoEmbed2v2` + `MatchReportView2v2` to all 4 players
- `_on_match_aborted_2v2` — sends `MatchAbortedEmbed2v2`, clears state for all 4
- `_on_match_abandoned_2v2` — sends `MatchAbandonedEmbed2v2`, clears state for all 4
- `_on_match_completed_2v2` — sends `MatchFinalizedEmbed2v2` to all 4, posts match log
- `_on_match_conflict_2v2` — sends `MatchConflictEmbed2v2` to all 4, posts match log

Helper `_clear_match_state_all_2v2(uids)` removes confirm/abort buttons and disables report dropdowns for all 4 players in one pass (combines the 1v1 `_clear_match_found_messages_low` + `_clear_match_state_low` pattern).

**Why:** Injecting `game_mode` at the broadcast source is simpler and more explicit than inferring mode from field names (e.g. checking for `team_1_player_1_discord_uid` vs `player_1_discord_uid`). The default of `"1v1"` ensures all existing 1v1 broadcasts continue to work with no changes.

---

## 8. Bot UI — Embeds, Views, Commands

### Embeds (`bot/components/embeds.py`)

New 2v2 embeds:
- `QueueSetupEmbed2v2` — shown alongside the queue setup view
- `MatchInfoEmbed2v2` — match details for all 4 players after confirmation (teams, races, map, server)
- `MatchAbortedEmbed2v2`, `MatchAbandonedEmbed2v2`, `MatchFinalizedEmbed2v2`, `MatchConflictEmbed2v2` — terminal state embeds

**Why:** Separate embed classes for each terminal state keep rendering logic isolated and testable. The 4-player case requires slightly different field layout (two team blocks instead of one) so a dedicated `MatchInfoEmbed2v2` is cleaner than parametrizing `MatchInfoEmbed`.

### Views (`bot/components/views.py`)

- `AllRaceSelect` — a select covering all BW + SC2 races; used twice in `QueueSetupView2v2` (one for leader, one for member)
- `MapVetoSelect2v2` — map veto select for the 2v2 map pool
- `QueueSetupView2v2` — 4-row view (queue type buttons / leader race / member race / map vetoes); derives composition type from the two race selections, saves to `PUT /preferences_2v2`, then calls `POST /queue_2v2/join`
- `MatchFoundView2v2` — Confirm + Abort buttons; calls `PUT /matches_2v2/{match_id}/confirm` or `abort`
- `MatchReportView2v2` — report dropdown with `team_1_win`, `team_2_win`, `draw` options

**Discord 5-row constraint:** Row 0 has action buttons. Rows 1–3 have the three composition selects (Pure BW, Mixed, Pure SC2). Row 4 has map vetoes. Pure BW and Pure SC2 selects use duplicate options (\_1/\_2 suffixes) so both players can pick the same race for mirror matchups. The mixed select has 6 unique options (one per race). Selection order determines role: first pick = leader, second pick = member.

### Commands

- `/queue game_mode:2v2` (`bot/commands/user/queue_command.py`) — verifies party membership via `GET /party_2v2/{uid}`, loads saved preferences from `GET /preferences_2v2/{discord_uid}`, restores the last-used composition, shows `QueueSetupEmbed2v2` + `QueueSetupView2v2`
- `/party invite {user}` — sends invite to backend, DMs the invitee
- `/party leave` — removes the caller from their party
- `/party status` — shows current party state

**Why:** Restoring saved preferences on `/queue2v2` open mirrors `/queue` behavior for 1v1 and reduces friction for regular players.

---

## 9. Replay System (2v2)

**What:** `parse_replay_2v2()` in `backend/algorithms/replay_parser.py` and `verify_replay_2v2()` in `backend/algorithms/replay_verifier.py` — parse and verify 2v2 replays. The parser uses `sc2reader` identical to the 1v1 parser; the verifier checks 4 players instead of 2.

**Wired:** The bot's replay upload handler (`bot/helpers/replay_handler.py`) detects 2v2 matches and routes to `POST /matches_2v2/{match_id}/replay`. The endpoint runs the full 8-step flow (validate, parse in ProcessPoolExecutor, insert pending row, upload to storage, update status, update match refs, verify, auto-resolve).

---

## 10. Admin Tools (2v2)

**What:** Full admin support for 2v2 matches:
- `GET /admin/matches_2v2/{match_id}` — fetch match + 4 player rows + admin info
- `PUT /admin/matches_2v2/{match_id}/resolve` — admin resolve 2v2 match conflicts
- `GET /admin/snapshot_2v2` — queue, active matches, parties, DataFrame stats
- `/admin match {match_id}` — auto-detects 1v1 vs 2v2 and shows appropriate embed
- `/admin resolve {match_id} {result}` — supports 2v2 result codes (`team_1_win`, `team_2_win`, `draw`, `invalidated`)

Bot embeds: `AdminMatchEmbed2v2`, `AdminResolution2v2Embed`, `QueueSnapshotEmbed2v2`, `MatchesEmbed2v2`, `PartiesEmbed`.

**Why:** Admins need visibility into 2v2 match state and the ability to resolve conflicts, same as 1v1.

---

## 11. Localization

**What:** All 2v2 UI strings (party commands, queue setup, admin embeds, error messages) are localized via the `t()` function with keys in `data/locales/`. All six locale files (`enUS`, `base`, `koKR`, `ruRU`, `esMX`, `zhCN`) are kept in sync.

---

## What Is Not Yet Implemented

- **Party WS events** — party invite/accept/leave are synchronous (request/response); there are no WS broadcasts for party state changes. The bot handles party feedback in the command response and sends a manual DM to the other player.
- **Party invite stale button handling** — if the bot restarts, old invite DM buttons hit a dead invite with no graceful "invite no longer valid" message.
- **`/profile` 2v2 stats** — profile only shows 1v1 MMR; no `mmrs_2v2` display yet.
- **`/owner mmr` for 2v2** — no admin setter for pair MMR (would need to target a pair, not an individual).
- **`/activity` 2v2** — command shows "2v2 (soon)" but rejects with unsupported game mode.
- **`/notifyme` 2v2** — only wired for `notify_queue_1v1`; 2v2 queue activity notifications not yet supported.
- **2v2 MMR seeding from 1v1** — new pairs start at default 1500; plan suggested optional seeding from avg individual 1v1 MMR.
- **3v3, FFA** — no planned work yet
