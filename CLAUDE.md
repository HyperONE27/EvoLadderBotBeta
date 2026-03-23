# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

EvoLadderBotBeta is a Discord-based ladder (ranked matchmaking) system for the SC: Evo Complete StarCraft II mod. It is split into two separate processes that communicate over HTTP and WebSocket:

1. **Backend** — a FastAPI service holding all game state in-memory (Polars DataFrames) backed by Supabase (PostgreSQL). Exposed at `BACKEND_URL`.
2. **Bot** — a discord.py client that handles all Discord interactions and forwards state-changing actions to the backend via HTTP calls (using `aiohttp`). Receives real-time events from the backend via WebSocket.

1v1 mode is fully implemented. 2v2 mode is partially implemented (matchmaker, party system, queue/match lifecycle, bot UI, preferences, replay upload, and leaderboard display are live; admin tools are not yet wired). 3v3 and FFA are planned but not yet in the codebase.

## Running the Project

```bash
# Activate the venv first
source .venv/bin/activate

# Run the backend (FastAPI)
uvicorn backend.api.app:app --reload

# Run the bot (in a separate terminal)
python -m bot.core.app
```

## Linting / Type Checking

Run local CI with:
```bash
make quality
```
This runs `ruff check --fix`, `ruff format`, then `mypy backend bot common`.

Install dev dependencies with:
```bash
pip install -r requirements-dev.txt
```

CI (`.github/workflows/ci.yml`) runs on push/PR to main: ruff check + format check + mypy. Python 3.14.

## Environment Variables

Both processes require a `.env` file in the project root. Required variables:

**Backend:**
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_BUCKET_NAME` (replay file storage)

**Bot:**
- `BOT_TOKEN`
- `BACKEND_URL`
- `MATCH_LOG_CHANNEL_ID`

**Optional:**
- `REPLAY_WORKER_PROCESSES` (default: 2) — number of `ProcessPoolExecutor` workers for replay parsing
- `BOT_ICON_URL` — public HTTPS URL for the footer icon on branded embeds (`bot/helpers/embed_branding.py`); omit or leave empty for text-only footer

## Architecture

### Two-Process Design

```
Discord Users
     |
     v
[Bot Process]  --HTTP + WS-->  [Backend Process]
  discord.py                      FastAPI + Supabase
  bot/core/app.py                 backend/api/app.py
```

- The bot handles all Discord UI (slash commands, buttons, embeds, views) and calls the backend for any operation that reads or writes game state.
- The backend is the single source of truth. It loads the entire Supabase database into Polars DataFrames at startup (`StateManager`) and serves queries sub-millisecond from memory. Writes go to Supabase via `DatabaseWriter`.
- Real-time events (match found, confirmed, completed, etc.) flow from backend to bot over a WebSocket at `/ws`.

### Backend Internals

- **`Backend`** (`backend/core/bootstrap.py`) — top-level singleton created at FastAPI startup. Holds `StateManager`, `Orchestrator`, `DatabaseWriter`, `StorageWriter`, and a `ProcessPoolExecutor` for replay parsing. `ensure_pool_healthy()` submits a no-op to the pool before each replay parse and detects dead workers (C extension segfaults in `sc2reader` permanently break Python's stdlib executor); if the pool is broken it is replaced automatically.
- **`StateManager`** (`backend/orchestrator/state.py`) — holds all in-memory state: Polars DataFrames for each DB table (admins, players, notifications, events, matches_1v1, mmrs_1v1, preferences_1v1, replays_1v1, matches_2v2, mmrs_2v2, preferences_2v2, replays_2v2), static JSON data (countries, maps, mods, races, regions, etc.), live queue lists (`queue_1v1`, `queue_2v2`), leaderboard lists, and the `parties_2v2` dict (keyed by leader UID). Populated at startup via `DatabaseReader.load_all_tables()` and `JSONLoader`.
- **`Orchestrator`** (`backend/orchestrator/orchestrator.py`) — the public API surface of the backend. Delegates reads to `StateReader` and writes to `TransitionManager`.
- **`StateReader`** (`backend/orchestrator/reader.py`) — all read operations delegated to lookup modules.
- **`TransitionManager`** (`backend/orchestrator/transitions/`) — performs all mutations on `StateManager` DataFrames, then queues async writes back to Supabase via `DatabaseWriter`. Split into submodules: `_base`, `_admin`, `_leaderboard`, `_match`, `_match_2v2`, `_mmr`, `_notifications`, `_party`, `_player`, `_queue`, `_replay`.
- **Lookups** (`backend/lookups/`) — one module per domain (players, matches, mmr, replays, admin, preferences_1v1, preferences_2v2, notifications). Each `init_*` function registers a global `_state_manager` at startup and exposes lookup functions.
- **`DatabaseReader`** / **`DatabaseWriter`** (`backend/database/database.py`) — thin wrappers around the Supabase Python client. `DatabaseReader.load_all_tables()` is called once at startup; writes happen via `DatabaseWriter`. Reads use anon key, writes use service_role_key.
- **`StorageWriter`** (`backend/database/storage.py`) — handles replay file uploads to Supabase Storage bucket. Path format: `replays/{match_id}/{discord_uid}/{timestamp}_{hash}.SC2Replay`.
- **Table schemas** are defined as Polars `DataType` dicts in `backend/domain_types/dataframes.py` (`TABLE_SCHEMAS` registry) and used for strict validation on load. TypedDict row types (`AdminsRow`, `PlayersRow`, `Matches1v1Row`, etc.) are in the same file.
- **Ephemeral types** (`backend/domain_types/ephemeral.py`) — 1v1: `QueueEntry1v1`, `MatchCandidate1v1`, `MatchParams1v1`, `LeaderboardEntry1v1`. 2v2: `PendingPartyInvite2v2`, `PartyEntry2v2`, `QueueEntry2v2`, `MatchCandidate2v2`, `MatchParams2v2`, `LeaderboardEntry2v2`. All in-memory only, not persisted.
- **Authorization** (`backend/orchestrator/authorization.py`) — exists but is currently empty; authorization checks happen on the bot side via `bot/helpers/checks.py`.

### Backend API Endpoints (`backend/api/endpoints.py`)

**Admin:**
- `PUT /admin/ban` — toggle ban status
- `PUT /admin/statusreset` — reset player queue status (if stuck)
- `GET /admin/matches_1v1/{match_id}` — full match + replay details + verification
- `PUT /admin/matches_1v1/{match_id}/resolve` — resolve match conflicts
- `GET /admin/snapshot_1v1` — queue & active matches snapshot + DataFrame stats

**Owner:**
- `PUT /owner/admin` — toggle admin role (promote/demote)
- `PUT /owner/mmr` — directly set a player's MMR for a race

**User/Player:**
- `GET /profile/{discord_uid}` — player info + all MMR rows
- `GET /players/{discord_uid}` — player row
- `GET /admins/{discord_uid}` — admin row (used by bot for permission checks)
- `GET /mmrs_1v1/{discord_uid}` and `GET /mmrs_1v1/{discord_uid}/{race}` — MMR lookups
- `GET /preferences_1v1/{discord_uid}` and `PUT /preferences_1v1` — saved race & veto choices
- `GET /preferences_2v2/{discord_uid}` and `PUT /preferences_2v2` — saved 2v2 composition & veto choices

**Queue & Match Lifecycle (1v1):**
- `POST /queue_1v1/join` — join queue with races/MMRs/map vetoes
- `DELETE /queue_1v1/leave` — leave queue
- `GET /queue_1v1/stats` — population breakdown (bw_only, sc2_only, both)
- `PUT /matches_1v1/{match_id}/confirm` — player confirms match
- `PUT /matches_1v1/{match_id}/abort` — player aborts before confirmation
- `PUT /matches_1v1/{match_id}/report` — report match result

**Queue & Match Lifecycle (2v2):**
- `POST /queue_2v2/join` — party leader submits composition choices; both players enter queue
- `DELETE /queue_2v2/leave` — leader triggers; both removed from queue
- `PUT /matches_2v2/{match_id}/confirm` — player confirms; broadcasts `both_confirmed` when all 4 confirm
- `PUT /matches_2v2/{match_id}/abort` — player aborts; broadcasts `match_aborted`
- `PUT /matches_2v2/{match_id}/report` — team reports result; broadcasts `match_completed` or `match_conflict`

**Party (2v2):**
- `PUT /party_2v2/invite` — create a pending party invite
- `PUT /party_2v2/respond` — accept or decline an invite; accept sets both players to `in_party`
- `DELETE /party_2v2/leave` — disband party, both players return to `idle`
- `GET /party_2v2/{discord_uid}` — current party state for a player

**Setup:**
- `PUT /commands/setup` — upsert player profile (name, alts, battletag, nationality, location, language)
- `PUT /commands/setcountry` — update country
- `PUT /commands/termsofservice` — accept/reject ToS

**Replay:**
- `POST /matches_1v1/{match_id}/replay` — 7-step flow: validate, parse (in ProcessPoolExecutor), insert pending row, upload to storage, update status, update match refs, run verifier

**Leaderboard & Analytics:**
- `GET /leaderboard_1v1` — current 1v1 leaderboard with letter ranks
- `GET /analytics/queue_joins` — bucketed queue join counts for `/activity` chart

**Notifications:**
- `GET /notifications/{discord_uid}` — notification preferences for a player
- `PUT /notifications` — upsert notification preferences (e.g. `/notifyme` opt-in)

### WebSocket Events

The backend broadcasts events via `ConnectionManager` (`backend/api/websocket.py`) at `/ws`. The bot listens via `bot/core/ws_listener.py` (auto-reconnects on disconnect with 5s backoff).

Eight event types:
| Event | Meaning |
|---|---|
| `match_found` | Matchmaker paired two players / two teams |
| `both_confirmed` | Both players (1v1) or all four players (2v2) confirmed |
| `match_aborted` | A player explicitly pressed "Abort Match" |
| `match_abandoned` | Confirmation window expired (60s timeout) |
| `match_completed` | Both sides agreed on match result |
| `match_conflict` | Sides reported conflicting results |
| `leaderboard_updated` | Leaderboard rebuilt after a match resolution |
| `queue_join_activity` | Anonymous notification to opted-in subscribers that someone queued |

The first six are match lifecycle events (same for both 1v1 and 2v2). The last two are system-level broadcasts.

**Game-mode routing:** 2v2 broadcasts include `"game_mode": "2v2"` in the payload. 1v1 broadcasts omit the field. The bot's `_handle_message` reads `data.get("game_mode", "1v1")` to dispatch to the correct 1v1 or 2v2 handler set. This means 1v1 broadcasts require no changes to support 2v2.

### Bot Internals

- **`Bot`** (`bot/core/bootstrap.py`) — top-level singleton. Holds a `Cache` with the same JSON static data as the backend (loaded independently).
- **`Cache`** — holds static JSON data + runtime tracking: `active_searching_messages`, `active_searching_views`, `active_match_info`, `active_match_messages` (maps discord_uid to Discord message objects for in-flight match lifecycle).
- **`bot/core/app.py`** — entry point. Creates the `discord.Client` and `app_commands.CommandTree`, registers slash commands, starts WS listener, initializes message queue, handles replay uploads in `on_message()` for DMs with `.SC2Replay` attachments.
- HTTP calls to the backend are made with the `aiohttp` session managed in `bot/core/http.py`.
- **Message Queue** (`bot/core/message_queue.py`) — two-tier priority queue for non-interaction Discord API calls. High-priority: player-facing sends (match-found DMs, match info). Low-priority: terminal event DMs, match log posts, embed edits. Single worker, 40 msgs/sec rate limit, max 3 retries per job. Interaction endpoints (response, followup, edit_original_response) are NOT routed through this queue.

### Bot Commands

Commands are organized under `bot/commands/{user,admin,owner}/`. Each command file exports a `register_*_command(tree)` function.

**User Commands:**
- `/setup` — modal for player_name, alt_player_names, battletag, nationality, location, language
- `/setcountry` — set/update country
- `/queue` — choose races (BW, SC2, or both) + up to 4 map vetoes, then enter 1v1 queue
- `/queue2v2` — choose composition (leader + member races) + map vetoes, then enter 2v2 queue (requires active party)
- `/termsofservice` — accept/reject ToS
- `/profile` — view player data + MMR breakdowns
- `/greeting` — greeting/welcome command
- `/notifyme` — opt-in to DM notifications when someone joins the queue
- `/activity` — line chart of queue join attempts over time (DM-only, uses `/analytics/queue_joins`)
- `/leaderboard` — 1v1 leaderboard with letter ranks and MMR
- `/party invite {user}` — invite a player to form a 2v2 party
- `/party leave` — leave current party
- `/party status` — show current party state

**Admin Commands (`/admin <subcommand>`):**
- `ban` — toggle ban status
- `snapshot` — queue snapshot + active matches + DataFrame stats
- `match {match_id}` — full match details + replay verification results
- `resolve {match_id} {result}` — resolve match conflict
- `statusreset` — reset player queue status

**Owner Commands (`/owner <subcommand>`):**
- `admin {discord_uid}` — promote/demote admin
- `mmr {discord_uid} {race} {new_mmr}` — directly set MMR

### Bot Permission Checks (`bot/helpers/checks.py`)

All checks hit the backend API to verify permissions:
- `check_if_dm()` — enforce DMs-only (sync)
- `check_if_banned()` — GET /players/{uid}, check is_banned (async)
- `check_if_admin()` — GET /admins/{uid}, role != "inactive" (async)
- `check_if_owner()` — GET /admins/{uid}, role == "owner" (async)

Custom exceptions: `NotInDMError`, `BannedError`, `NotAdminError`, `NotOwnerError`, `NotAcceptedTosError`, `NotCompletedSetupError`, `AlreadyQueueingError`, `NameNotUniqueError`.

### Bot UI Components (`bot/components/`)

- `embeds.py` — reusable Discord embed builders
- `views.py` — Discord UI views (button/dropdown layouts)
- `buttons.py` — reusable button components
- `replay_embed.py` — embed for replay upload details

### Static Data

All game data lives under `data/core/` as JSON:
- `countries.json`, `regions.json`, `cross_table.json` — geographic and server routing data
- `maps.json`, `mods.json`, `races.json`, `emotes.json` — game content lookups

Locale strings are under `data/locales/` (enUS, koKR, zhCN, esMX, ruRU) — framework in place but not yet wired to commands.

`common/loader.py` (`JSONLoader`) loads all core JSON at startup for both processes. `common/json_types.py` contains TypedDict definitions for all JSON structures. `common/protocols.py` defines a `StaticDataSource` protocol satisfied by both `StateManager` and `Cache`, used to initialize `common/lookups/` modules.

### Common Lookups (`common/lookups/`)

Shared lookup modules used by both backend and bot: `country_lookups`, `region_lookups`, `race_lookups`, `map_lookups`, `mod_lookups`, `emote_lookups`, `cross_table_lookups`. Each has a global cache, init function, and lookup functions.

### Logging

Both processes use `structlog` configured via `common/logging/config.py`. Console output (pretty-printed), UTC ISO timestamps, service name bound per process. Silences noisy third-party loggers (discord.py, aiohttp, httpx, uvicorn).

### Datetime Handling (`common/datetime_helpers.py`)

Canonical form: UTC-aware `datetime(tzinfo=timezone.utc)`. All timestamps in Polars are `Datetime("us", "utc")`.

Public API: `utc_now()`, `ensure_utc(value)` (accepts datetime/ISO string/None), `to_iso()`, `to_discord_timestamp()`, `to_display()`.

### MMR / Ratings

ELO-like system configured in `backend/core/config.py`:
- Default MMR: 1500
- Divisor: 500 (NOT the standard 400; a 100-point gap gives ~62% expected win rate)
- K-factor: 40

`backend/algorithms/ratings_1v1.py`: `get_new_ratings(p1_mmr, p2_mmr, match_result)` computes new MMRs. Result codes: 0=draw, 1=player_1_win, 2=player_2_win.

### Matchmaking

Both matchmakers are stateless pure functions and run at the top of every minute (60-second waves) in `backend/api/app.py`. After match creation a 60-second confirmation timeout is started.

**1v1 Matchmaker** (`backend/algorithms/matchmaker.py`) — `run_matchmaking_wave(queue)` returns `(remaining, matches)`.

Algorithm:
1. Categorize queue into bw_only, sc2_only, and both-race pools
2. Equalize pools: assign "both" players to balance BW/SC2 by population and skill (3-phase: hard population balance, alternating distribution, soft skill rebalance with 50 MMR threshold)
3. Smaller pool leads, larger follows. Build candidate pairs within each player's MMR window
4. **MMR window:** `BASE_MMR_WINDOW (100) + wait_cycles * MMR_WINDOW_GROWTH_PER_CYCLE (50)`
5. **Scoring:** `score = mmr_diff^2 - (2^wait_factor * 20.0)` — lower is better. Exponential wait bonus guarantees long-waiters eventually match regardless of MMR gap
6. **Optimal pairing via Hungarian algorithm** (Kuhn-Munkres, O(n^3))

**2v2 Matchmaker** (`backend/algorithms/matchmaker_2v2.py`) — `run_matchmaking_wave_2v2(queue)` returns `(remaining, matches)`. Queue entries are per party (not per player); each entry carries all three composition slots (pure BW, pure SC2, mixed).

Algorithm:
1. **Compatibility check:** two parties are compatible if one can play BW while the other plays SC2 (either order), or if both declared mixed compositions
2. **Cost matrix:** same scoring formula as 1v1 (`mmr_diff^2 - wait_bonus`); incompatible pairs get sentinel cost
3. **Optimal pairing** via Hungarian algorithm (O(n^3)), same as 1v1
4. **Composition resolution:** after pairing, determine which team plays BW and which plays SC2; if both can swap, randomise

MMR for 2v2 is per **unique player pair** (stored in `mmrs_2v2` with the smaller UID first), not per individual player or race.

**Match Parameters** — `backend/algorithms/match_params.py` (1v1) and `backend/algorithms/match_params_2v2.py` (2v2). Random map from non-vetoed pool, in-game channel `SCEvoLadder`. 1v1 resolves server from `cross_table[region_1][region_2]`. 2v2 resolves server by majority vote across four player regions (deduplicates, then falls back to pair lookup or most common region).

### Replay System

- **Parser** (`backend/algorithms/replay_parser.py`): Uses `sc2reader` to extract player names, races, map, timestamp, duration, observers, cache handles, game settings. Runs in `ProcessPoolExecutor` to avoid blocking the event loop.
- **Verifier** (`backend/algorithms/replay_verifier.py`): Compares parsed replay against expected match settings (races, map, mod via cache handles, timestamp, observers, game privacy/speed/duration/locked alliances). Results are informational unless `_ENABLE_REPLAY_VALIDATION=True` in the bot (currently True — report dropdown is locked until replay passes race checks).
- **Upload flow:** Bot receives `.SC2Replay` via DM attachment → POST to backend → parse → insert pending row → upload to Supabase Storage → update status → update match refs → verify → return results.

### Game Stats (`backend/algorithms/game_stats.py`)

`count_game_stats(matches_df, discord_uid, race)` computes games_played/won/lost/drawn from the matches DataFrame. Only counts matches with countable results (excludes conflict, abort, abandoned, etc.).

### Database Schema (`backend/database/schema.sql`)

12 tables: `admins`, `players`, `notifications`, `events`, `matches_1v1`, `mmrs_1v1`, `preferences_1v1`, `replays_1v1`, `matches_2v2`, `mmrs_2v2`, `preferences_2v2`, `replays_2v2`.

Key constraints:
- Admin roles: `owner`, `admin`, `inactive`
- Player statuses: `idle`, `queueing`, `in_match`, `timed_out`, `in_party`
- Match modes: `1v1`, `2v2`, `FFA`
- Races: `bw_terran`, `bw_zerg`, `bw_protoss`, `sc2_terran`, `sc2_zerg`, `sc2_protoss`
- Match results: `player_1_win`, `player_2_win`, `draw`, `conflict`, `abort`, `abandoned`, `invalidated`, `no_report`
- Languages: `enUS`, `esMX`, `koKR`, `ruRU`, `zhCN`

### Deployment

Deployed on Railway as two separate services:
- Backend (`backend/railway.json`): `uvicorn backend.api.app:app --host 0.0.0.0 --port 8080 --workers 1`
- Bot (`bot/railway.json`): `python -m bot.core.app`

Both use Railpack builder with restart-on-failure (max 10 retries).

### Key Dependencies

`discord.py`, `fastapi`, `polars`, `supabase`, `sc2reader`, `xxhash`, `uvicorn`, `python-dotenv`, `python-multipart`, `structlog`

Dev: `ruff`, `mypy`, `pytest`

### Naming Conventions

- **UIDs:** Never use bare `_uid`. Always use `_discord_uid` (e.g. `team_1_player_1_discord_uid`, not `team_1_player_1_uid`).
- **Names:** Always specify `_player_name` or `_discord_username`, not bare `_name`. Exception: if the field already contains the word "player" (e.g. `player_1_name`), the distinction is unnecessary.

These rules apply to all schema types: SQL tables, Polars schemas, TypedDicts, and ephemeral types.

### Localization

Locale strings live in `data/locales/`. When adding or updating keys in any locale file (e.g. `enUS.json`), **all other locale files** (`base.json`, `koKR.json`, `ruRU.json`, `esMX.json`, `zhCN.json`) must be updated with the same keys and appropriate translations. Keys in all locale files must be sorted in lexicographic order.

### When Making Changes

- Run `make quality` to run local CI (ruff + mypy) and make sure all your changes pass.
- Write a descriptive commit title (imperative mood, e.g. "fix queue heartbeat race condition") and a short body explaining *why* when the change isn't obvious. No bare `"."` commits.
- Both matchmakers are stateless and pure — they can be unit-tested with synthetic `QueueEntry1v1` / `QueueEntry2v2` lists without any I/O.
- Replay parsing runs in a subprocess pool — avoid adding async or event-loop-dependent code to `replay_parser.py`.
- All DataFrame mutations go through `TransitionManager` — never modify `StateManager` DataFrames directly.
- WebSocket events are the only way the bot learns about match lifecycle changes — if adding a new match state transition, add a corresponding WS broadcast.
- The `common/` package is shared between backend and bot — changes here affect both processes.
- Admin roles are seeded from the `ADMINS` env var (no longer required — admins table is loaded from Supabase). The `ADMINS` env var reference in older docs is outdated.

### Testing

Invariant-based test suite in `tests/`. Tests check structural properties (zero-sum, conservation, optimality, symmetry) rather than encoding specific numerical outcomes, so they survive tuning changes. See `docs/testing.md` for philosophy and organisation.

```bash
python -m pytest tests/ -v
```

`tests/conftest.py` sets dummy env vars so algorithm imports work without `.env`.

### Not Yet Implemented

These items appear in planning docs or have stub code but are not functional:
- 3v3, FFA modes
- `/help` and `/prune` commands (empty stub files)
