# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

EvoLadderBotBeta is a Discord-based ladder (ranked matchmaking) system for the SC: Evo Complete StarCraft II mod. It is split into three separate processes:

1. **Backend** — a FastAPI service holding all game state in-memory (Polars DataFrames) backed by Supabase (PostgreSQL). Exposed at `BACKEND_URL`.
2. **Bot** — a discord.py client that handles all Discord interactions and forwards state-changing actions to the backend via HTTP calls (using `aiohttp`). Receives real-time events from the backend via WebSocket.
3. **Channel Manager** — a lightweight FastAPI service that creates and deletes Discord voice/text channels for matches via the Discord REST API directly. Called by the backend; optional (channel creation is skipped if `CHANNEL_MANAGER_URL` is unset).

1v1 mode is fully implemented. 2v2 mode is partially implemented (matchmaker, party system, queue/match lifecycle, bot UI, preferences, replay upload, and leaderboard display are live; admin tools are not yet wired). 3v3 and FFA are planned but not yet in the codebase.

## Running the Project

```bash
# Activate the venv first
source .venv/bin/activate

# Run the local run script
make run
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

**Channel Manager:**
- `CHANNEL_MANAGER_BOT_TOKEN` — Discord bot token for the channel manager (may differ from bot's token)
- `DISCORD_GUILD_ID`, `DISCORD_CHANNEL_CATEGORY_ID` — where to create match channels
- `DISCORD_STAFF_ROLE_IDS` — comma-separated role IDs granted access to match channels
- `SUPABASE_SERVICE_ROLE_KEY` — used for any DB writes the channel manager makes

**Optional:**
- `CHANNEL_MANAGER_URL` — URL of the channel manager service; if unset, channel creation is silently skipped
- `REPLAY_WORKER_PROCESSES` (default: 2) — number of `ProcessPoolExecutor` workers for replay parsing
- `BOT_ICON_URL` — public HTTPS URL for the footer icon on branded embeds (`bot/helpers/embed_branding.py`); omit or leave empty for text-only footer

## Architecture

### Three-Process Design

```
Discord Users
     |
     v
[Bot Process]  --HTTP + WS-->  [Backend Process]  --HTTP-->  [Channel Manager]
  discord.py                      FastAPI + Supabase            FastAPI + discord REST
  bot/core/app.py                 backend/api/app.py            channel_manager/app.py
```

- The bot handles all Discord UI (slash commands, buttons, embeds, views) and calls the backend for any operation that reads or writes game state.
- The backend is the single source of truth. It loads the entire Supabase database into Polars DataFrames at startup (`StateManager`) and serves queries sub-millisecond from memory. Writes go to Supabase via `DatabaseWriter`.
- Real-time events (match found, confirmed, completed, etc.) flow from backend to bot over a WebSocket at `/ws`.
- The channel manager is called by the backend (not the bot) when a match is created or ends, to create/delete the corresponding Discord channel.

### Backend Internals

- **`Backend`** (`backend/core/bootstrap.py`) — top-level singleton created at FastAPI startup. Holds `StateManager`, `Orchestrator`, `DatabaseWriter`, `StorageWriter`, and a `ProcessPoolExecutor` for replay parsing. `ensure_pool_healthy()` detects dead workers (sc2reader segfaults can permanently break Python's stdlib executor) and replaces the pool automatically.
- **`StateManager`** (`backend/orchestrator/state.py`) — holds all in-memory state: Polars DataFrames for each DB table (admins, players, notifications, events, matches_1v1, mmrs_1v1, preferences_1v1, replays_1v1, matches_2v2, mmrs_2v2, preferences_2v2, replays_2v2), static JSON data, live queue lists (`queue_1v1`, `queue_2v2`), leaderboard lists, and the `parties_2v2` dict (keyed by leader UID). Populated at startup via `DatabaseReader.load_all_tables()` and `JSONLoader`.
- **`Orchestrator`** (`backend/orchestrator/orchestrator.py`) — the public API surface of the backend. Delegates reads to `StateReader` and writes to `TransitionManager`.
- **`TransitionManager`** (`backend/orchestrator/transitions/`) — performs all mutations on `StateManager` DataFrames, then queues async writes back to Supabase via `DatabaseWriter`. Split into submodules: `_base`, `_admin`, `_leaderboard`, `_match`, `_match_2v2`, `_mmr`, `_notifications`, `_party`, `_player`, `_queue`, `_replay`.
- **Lookups** (`backend/lookups/`) — one module per domain (players, matches, mmr, replays, admin, preferences_1v1, preferences_2v2, notifications). Each `init_*` function registers a global `_state_manager` at startup.
- **`DatabaseReader`** / **`DatabaseWriter`** (`backend/database/database.py`) — thin wrappers around the Supabase Python client. Reads use anon key, writes use service_role_key. All datetime values must be serialized to ISO strings before sending to Supabase — use `_serialise_event_row()` or `utc_now().isoformat()` explicitly; never pass raw `datetime` objects.
- **`StorageWriter`** (`backend/database/storage.py`) — handles replay file uploads to Supabase Storage. Path format: `replays/{match_id}/{discord_uid}/{timestamp}_{hash}.SC2Replay`.
- **Table schemas** are defined as Polars `DataType` dicts in `backend/domain_types/dataframes.py` (`TABLE_SCHEMAS` registry). TypedDict row types (`AdminsRow`, `PlayersRow`, etc.) are in the same file.
- **Ephemeral types** (`backend/domain_types/ephemeral.py`) — queue entries, match candidates, match params, leaderboard entries for both 1v1 and 2v2. All in-memory only, not persisted.

### Backend API Endpoints (`backend/api/endpoints.py`)

The full route list is best read from `endpoints.py` directly. High-level groups:
- `/admin/*`, `/owner/*` — privileged operations (ban, resolve, snapshot, set MMR, toggle admin)
- `/players/*`, `/admins/*`, `/profile/*`, `/mmrs_1v1/*`, `/preferences_*`, `/notifications/*` — player data reads/writes
- `/queue_1v1/*`, `/queue_2v2/*`, `/matches_1v1/*`, `/matches_2v2/*` — queue join/leave and match lifecycle (confirm, abort, report)
- `/party_2v2/*` — party invite, respond, leave, status
- `/commands/setup`, `/commands/setcountry`, `/commands/termsofservice` — setup flow
- `/leaderboard_1v1`, `/analytics/queue_joins` — leaderboard and activity data
- `/ws` — WebSocket endpoint for bot ↔ backend real-time events

### WebSocket Events

The backend broadcasts events via `ConnectionManager` (`backend/api/websocket.py`) at `/ws`. The bot listens via `bot/core/ws_listener.py` (auto-reconnects with 5s backoff).

| Event | Meaning |
|---|---|
| `match_found` | Matchmaker paired two players / two teams |
| `both_confirmed` | All players confirmed the match |
| `match_aborted` | A player pressed "Abort Match" |
| `match_abandoned` | Confirmation window expired (60s timeout) |
| `match_completed` | Both sides agreed on match result |
| `match_conflict` | Sides reported conflicting results |
| `leaderboard_updated` | Leaderboard rebuilt after a match resolution |
| `queue_join_activity` | Anonymous DM to opted-in subscribers that someone queued |

**Game-mode routing:** 2v2 broadcasts include `"game_mode": "2v2"` in the payload. 1v1 broadcasts omit the field. The bot's `_handle_message` reads `data.get("game_mode", "1v1")` to dispatch to the correct handler set.

### Bot Internals

- **`Bot`** (`bot/core/bootstrap.py`) — top-level singleton. Holds a `Cache` with static JSON data and runtime tracking.
- **`Cache`** runtime fields:
  - `active_searching_messages` / `active_searching_views` — uid → message/view while player is in queue
  - `active_match_info` — uid → match data dict while player is in an active match
  - `active_match_found_messages` — uid → MatchFoundEmbed message (confirm/abort buttons)
  - `active_match_messages` — uid → MatchInfoEmbed message (updated after replay upload)
  - `leaderboard_1v1` / `leaderboard_2v2` — current leaderboard data pushed from backend via WS
  - `player_locales` — uid → locale code (e.g. `"enUS"`); populated on `/setup` and on `check_if_banned`
  - `player_presets` — uid → full player dict from backend; populated by `check_if_banned` so the setup flow can pre-populate fields without a second round-trip
- **`bot/core/app.py`** — entry point. Registers slash commands, starts WS listener, initializes message queue, handles replay uploads and new-player registration in `on_message()`.
- **Message Queue** (`bot/core/message_queue.py`) — two-tier priority queue for non-interaction Discord API calls. High-priority: match-found DMs and match info. Low-priority: terminal event DMs, match log posts, embed edits. Single worker, 40 msgs/sec, max 3 retries. Interaction endpoints (response, followup, edit_original_response) bypass this queue.

### Bot Commands

Commands are organized under `bot/commands/{user,admin,owner}/`. Each file exports a `register_*_command(tree)` function.

**User Commands:**
- `/setup` — multi-step flow: language selection → ToS acceptance → modal (player_name, alt_player_names, battletag) → nationality + location → notifications (1v1/2v2 queue ping opt-in) → preview → confirm
- `/setcountry` — update nationality
- `/queue` — choose game mode (1v1 or 2v2), races, map vetoes, then enter queue. 2v2 requires an active party.
- `/profile` — view player data and MMR breakdowns
- `/greeting` — greeting/welcome command
- `/activity` — line chart of queue join attempts over time (DM-only)
- `/leaderboard` — 1v1 leaderboard with letter ranks and MMR
- `/party invite {user}` — invite a player to form a 2v2 party
- `/party leave` — leave current party
- `/party status` — show current party state

**Admin Commands (`/admin <subcommand>`):**
- `ban` — toggle ban status
- `snapshot` — queue snapshot + active matches + DataFrame stats
- `match {match_id}` — full match details + replay verification results
- `resolve {match_id} {result}` — resolve match conflict
- `statusreset` — reset a stuck player's queue status

**Owner Commands (`/owner <subcommand>`):**
- `admin {discord_uid}` — promote/demote admin
- `mmr {discord_uid} {race} {new_mmr}` — directly set MMR

### Bot Permission Checks (`bot/helpers/checks.py`)

- `check_if_dm()` — enforce DMs-only (sync)
- `check_if_banned()` — GET /players/{uid}, checks `is_banned`; also caches the full player dict in `Cache.player_presets` and locale in `Cache.player_locales` as a side effect
- `check_if_admin()` — GET /admins/{uid}, role != `"inactive"`
- `check_if_owner()` — GET /admins/{uid}, role == `"owner"`

Custom exceptions: `NotInDMError`, `BannedError`, `NotAdminError`, `NotOwnerError`, `NotAcceptedTosError`, `NotCompletedSetupError`, `AlreadyQueueingError`, `NameNotUniqueError`.

### Static Data

All game data lives under `data/core/` as JSON: `countries.json`, `regions.json`, `cross_table.json`, `maps.json`, `mods.json`, `races.json`, `emotes.json`.

Locale strings are under `data/locales/` (base, enUS, esMX, koKR, ruRU, zhCN) and are actively used via `common/i18n.t()` throughout all embeds, views, and commands.

`common/loader.py` (`JSONLoader`) loads all core JSON at startup for both backend and bot. `common/protocols.py` defines a `StaticDataSource` protocol satisfied by both `StateManager` and `Cache`.

### Datetime Handling (`common/datetime_helpers.py`)

Canonical form: UTC-aware `datetime(tzinfo=timezone.utc)`. All timestamps in Polars are `Datetime("us", "utc")`.

Public API: `utc_now()`, `ensure_utc(value)` (accepts datetime/ISO string/None), `to_iso()`, `to_discord_timestamp()`, `to_display()`.

Always use these helpers. Never pass raw `datetime` objects to Supabase or JSON — they are not serializable.

### MMR / Ratings

ELO-like system configured in `backend/core/config.py`:
- Default MMR: 1500
- Divisor: 500 (NOT the standard 400; a 100-point gap gives ~62% expected win rate)
- K-factor: 40

`backend/algorithms/ratings_1v1.py`: `get_new_ratings(p1_mmr, p2_mmr, match_result)`. Result codes: 0=draw, 1=player_1_win, 2=player_2_win.

### Matchmaking

Both matchmakers are stateless pure functions (`backend/algorithms/matchmaker.py` and `matchmaker_2v2.py`) and run at the top of every minute (60-second waves) in `backend/api/app.py`. After match creation a 60-second confirmation timeout is started.

Both use the same scoring formula (`mmr_diff² - exponential_wait_bonus`) and optimal pairing via the Hungarian algorithm. The 1v1 matchmaker also balances BW/SC2 race pools before pairing. The 2v2 matchmaker works on per-party queue entries and resolves BW/SC2 composition assignment after pairing.

MMR for 2v2 is per **unique player pair** (stored in `mmrs_2v2` with the smaller UID first), not per individual.

**Match Parameters** — `backend/algorithms/match_params.py` (1v1) and `match_params_2v2.py` (2v2). Random non-vetoed map, in-game channel `SCEvoLadder`. Server resolved from `cross_table` for 1v1; majority vote across four player regions for 2v2.

### Replay System

- **Parser** (`backend/algorithms/replay_parser.py`): Uses `sc2reader` in a `ProcessPoolExecutor`. Never add async or event-loop code here.
- **Verifier** (`backend/algorithms/replay_verifier.py`): Compares parsed replay against expected match settings. Report dropdown is locked until replay passes race checks (`_ENABLE_REPLAY_VALIDATION=True` in the bot).
- **Upload flow:** Bot receives `.SC2Replay` via DM → POST to backend → parse → persist → upload to Supabase Storage → verify → return results.

### Database Schema (`backend/database/schema.sql`)

12 tables: `admins`, `players`, `notifications`, `events`, `matches_1v1`, `mmrs_1v1`, `preferences_1v1`, `replays_1v1`, `matches_2v2`, `mmrs_2v2`, `preferences_2v2`, `replays_2v2`.

### Deployment

Deployed on Railway as three separate services (backend, bot, channel manager). The backend uses `--workers 1` intentionally — single worker is required because all game state lives in-memory.

## Naming Conventions

- **UIDs:** Never use bare `_uid`. Always use `_discord_uid` (e.g. `team_1_player_1_discord_uid`, not `team_1_player_1_uid`).
- **Names:** Always specify `_player_name` or `_discord_username`, not bare `_name`. Exception: if the field already contains the word "player" (e.g. `player_1_name`), the distinction is unnecessary.

These rules apply to all schema types: SQL tables, Polars schemas, TypedDicts, and ephemeral types.

## Localization

Locale strings live in `data/locales/`. When adding or updating keys in any locale file (e.g. `enUS.json`), **all other locale files** (`base.json`, `koKR.json`, `ruRU.json`, `esMX.json`, `zhCN.json`) must be updated with the same keys and appropriate translations. Keys in all locale files must be sorted in lexicographic order.

## When Making Changes

- Run `make quality` to run local CI (ruff + mypy) and make sure all your changes pass.
- Write a descriptive commit title (imperative mood) and a short body explaining *why* when the change isn't obvious. No bare `"."` commits. Your work isn't done until you write a commit and push, unless explicitly told not to do one or both.
- All DataFrame mutations go through `TransitionManager` — never modify `StateManager` DataFrames directly.
- WebSocket events are the only way the bot learns about match lifecycle changes — if adding a new match state transition, add a corresponding WS broadcast.
- The `common/` package is shared between backend and bot — changes here affect both processes.
- Both matchmakers are stateless and pure — they can be unit-tested with synthetic queue entries without any I/O.
- Replay parsing runs in a subprocess pool — avoid async or event-loop-dependent code in `replay_parser.py`.
- You should use/add to the datetime helpers in common/ or the serialization helpers in backend/database/database.py instead of spinning your own implementations when working with datetimes — ESPECIALLY when JSON-serializing.

## Testing

Invariant-based test suite in `tests/`. Tests check structural properties (zero-sum, conservation, optimality, symmetry) rather than encoding specific numerical outcomes. See `docs/testing.md`.

```bash
python -m pytest tests/ -v
```

`tests/conftest.py` sets dummy env vars so algorithm imports work without `.env`.

## Not Yet Implemented

- 3v3, FFA modes
- `/help` and `/prune` commands (stub files exist but are not registered)