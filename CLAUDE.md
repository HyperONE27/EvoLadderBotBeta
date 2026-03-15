# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

EvoLadderBotBeta is a Discord-based ladder (ranked matchmaking) system for the SC: Evo Complete StarCraft II mod. It is split into two separate processes that communicate over HTTP:

1. **Backend** — a FastAPI service holding all game state in-memory (Polars DataFrames) backed by Supabase (PostgreSQL). Exposed at `BACKEND_URL`.
2. **Bot** — a discord.py client that handles all Discord interactions and forwards state-changing actions to the backend via HTTP calls (using `aiohttp`).

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

Install dev dependencies with:
```bash
pip install -r requirements-dev.txt
```

## Environment Variables

Both processes require a `.env` file in the project root. Required variables:

**Backend:**
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_BUCKET_NAME` (replay file storage)
- `ADMINS` (JSON array of `{discord_id, name, role}`)

**Bot:**
- `BOT_TOKEN`
- `BACKEND_URL`
- `MATCH_LOG_CHANNEL_ID`

## Architecture

### Two-Process Design

```
Discord Users
     │
     ▼
[Bot Process]  ──HTTP──▶  [Backend Process]
  discord.py                 FastAPI + Supabase
  bot/core/app.py            backend/api/app.py
```

- The bot handles all Discord UI (slash commands, buttons, embeds, views) and calls the backend for any operation that reads or writes game state.
- The backend is the single source of truth. It loads the entire Supabase database into Polars DataFrames at startup (`StateManager`) and serves queries sub-millisecond from memory. Writes go to Supabase via `DatabaseWriter`.

### Backend Internals

- **`Backend`** (`backend/core/bootstrap.py`) — top-level singleton created at FastAPI startup. Holds a `StateManager` and an `Orchestrator`.
- **`StateManager`** (`backend/orchestrator/state.py`) — holds all in-memory state: Polars DataFrames for each DB table, static JSON data (countries, maps, mods, regions, etc.), and the live queue list.
- **`Orchestrator`** (`backend/orchestrator/orchestrator.py`) — the public API surface of the backend. Delegates reads to `StateReader` and writes to `TransitionManager`.
- **`TransitionManager`** (`backend/orchestrator/transitions.py`) — performs all mutations on `StateManager` DataFrames, then queues async writes back to Supabase.
- **Lookups** (`backend/lookups/`) — one module per domain (players, matches, mmr, replays, etc.). Each `init_*` function registers itself against the `StateManager` at startup.
- **`DatabaseReader`** / **`DatabaseWriter`** (`backend/database/database.py`) — thin wrappers around the Supabase Python client. `DatabaseReader.load_all_tables()` is called once at startup; writes happen via `DatabaseWriter`.
- **Table schemas** are defined as Polars `DataType` dicts in `backend/domain_types/polars_dataframes.py` and used for strict validation on load.

### Bot Internals

- **`Bot`** (`bot/core/bootstrap.py`) — top-level singleton. Holds a `Cache` with the same JSON static data as the backend (loaded independently).
- **`bot/core/app.py`** — entry point. Creates the `discord.Client` and `app_commands.CommandTree`, registers slash commands, and starts the event loop.
- Commands are organized under `bot/commands/{user,admin,owner}/`. Each command file exports a `register_*_command(tree)` function.
- **`bot/components/`** — reusable Discord UI components: `embeds.py`, `views.py`, `buttons.py`.
- **`bot/helpers/decorators.py`** — command guard decorators (role checks, TOS checks, etc.).
- **`bot/helpers/i18n.py`** — i18n helper (not yet wired up).
- HTTP calls to the backend are made with the `aiohttp` session managed in `bot/core/http.py`.

### Static Data

All game data lives under `data/core/` as JSON:
- `countries.json`, `regions.json`, `cross_table.json` — geographic and server routing data
- `maps.json`, `mods.json`, `races.json`, `emotes.json` — game content lookups

Locale strings are under `data/locales/` (enUS, koKR, zhCN, esMX, ruRU) — not yet wired up.

`common/loader.py` (`JSONLoader`) loads all core JSON at startup for both processes. `common/json_types.py` contains TypedDict definitions for all JSON structures.

### MMR / Matchmaking

- Default MMR: 1500; divisor: 500; K-factor: 40 (ELO-like, configured in `backend/core/config.py`).
- Matchmaker runs in waves every 45 seconds. Window expands dynamically based on active player count.
- Server assignment is determined from `data/core/cross_table.json` which maps region pairs to recommended game servers.

### When Making Changes

- Don't forget to run `make quality` to run local CI and make sure all your changes pass!