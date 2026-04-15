# EvoLadder Bot

A Discord-based ranked matchmaking system for the [SC: Evo Complete](https://evomod.com/) StarCraft II mod. Players queue from DMs, get matched by MMR, confirm matches, play, upload replays, and see results — all through Discord.

1v1 is fully live. 2v2 is in beta. 3v3 and FFA are planned.

## How It Works

Three processes run together:

```
                      ┌───────────────┐
                      │ Discord Users │
                      └───────┬───────┘
                              │
              slash commands, buttons, replay DMs
                              │
                              ▼
                  ┌───────────────────────┐
                  │          Bot          │
                  │       discord.py      │
                  ├───────────────────────┤
                  │  slash commands       │
                  │  embeds & views       │
                  │  replay upload        │
                  │  message queue        │
                  └───────────┬───────────┘
                         HTTP │ ▲ WebSocket
                              │ │ (real-time match events)
                              ▼ │
┌─────────────────────────────────────────────────┐
│                    Backend                       │
│                FastAPI + Polars                  │
├──────────────────────┬──────────────────────────┤
│  matchmaker (60s)    │  in-memory DataFrames    │
│  ELO rating engine   │  writethrough to DB      │
│  replay parser       │  WebSocket broadcaster   │
└──────────┬───────────┴──────────┬───────────────┘
           │                      │
      read / write             HTTP (optional)
           │                      │
           ▼                      ▼
┌──────────────────┐  ┌─────────────────────────┐
│     Supabase     │  │    Channel Manager      │
│  PostgreSQL      │  │    FastAPI + Discord     │
│  + File Storage  │  │        REST API         │
└──────────────────┘  ├─────────────────────────┤
                      │  create / delete match  │
                      │  voice & text channels  │
                      └─────────────────────────┘
```

- **Bot** handles all Discord interaction (slash commands, buttons, DMs, replay uploads) and calls the backend over HTTP.
- **Backend** is the single source of truth. Loads the full database into Polars DataFrames at startup for sub-millisecond reads. Writes go to Supabase first, then update memory. Pushes real-time events to the bot over WebSocket.
- **Channel Manager** creates and deletes Discord voice/text channels for active matches. Called by the backend. Optional — skipped if `CHANNEL_MANAGER_URL` is unset.

Matchmaking runs every 60 seconds. It uses an ELO-like system (K=40, default 1500 MMR) with the Hungarian algorithm for optimal pairing.

## Setup

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/HyperONE/EvoLadderBotBeta.git
cd EvoLadderBotBeta
uv sync
```

Copy `.env.example` to `.env` (or create `.env` in the project root) and fill in:

| Variable | Required | Used by |
|---|---|---|
| `BOT_TOKEN` | yes | Bot |
| `BACKEND_URL` | yes | Bot |
| `MATCH_LOG_CHANNEL_ID` | yes | Bot |
| `SUPABASE_URL` | yes | Backend |
| `SUPABASE_ANON_KEY` | yes | Backend |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | Backend, Channel Manager |
| `SUPABASE_BUCKET_NAME` | yes | Backend |
| `CHANNEL_MANAGER_BOT_TOKEN` | no | Channel Manager |
| `DISCORD_GUILD_ID` | no | Channel Manager |
| `DISCORD_CHANNEL_CATEGORY_ID` | no | Channel Manager |
| `DISCORD_STAFF_ROLE_IDS` | no | Channel Manager |
| `CHANNEL_MANAGER_URL` | no | Backend |
| `REPLAY_WORKER_PROCESSES` | no | Backend (default: 2) |
| `BOT_ICON_URL` | no | Bot |

Then run all three processes:

```bash
make run
```

## Development

```bash
# Lint, format, type-check, and test
make quality

# Tests only
uv run python -m pytest tests/ -v
```

`make quality` runs ruff (check + format), mypy across `backend/ bot/ channel_manager/ common/`, then pytest. CI runs the same checks on push/PR to main.

## Project Structure

```
backend/
  api/          # FastAPI app, endpoints, WebSocket
  orchestrator/ # State management, transitions (writethrough to Supabase)
  algorithms/   # Matchmaker, MMR, replay parser/verifier, match params
  database/     # Supabase read/write/storage clients
  domain_types/ # Polars schemas, TypedDicts, ephemeral types
  lookups/      # Read-only query modules (players, matches, mmr, etc.)
  core/         # Config, bootstrap

bot/
  commands/     # Slash commands (user/, admin/, owner/)
  views/        # Discord UI components (buttons, modals, dropdowns)
  embeds/       # Embed builders
  helpers/      # Permission checks, branding, utilities
  core/         # App entry point, WS listener, message queue

channel_manager/  # Standalone FastAPI service for Discord channel lifecycle

common/         # Shared between backend and bot (i18n, datetime helpers, loader)
data/
  core/         # Game data JSON (maps, races, countries, emotes)
  locales/      # Translations (enUS, koKR, ruRU, esMX, zhCN)
tests/          # Invariant-based test suite
```

## Slash Commands

**Player:** `/setup`, `/queue`, `/profile`, `/leaderboard`, `/activity`, `/party invite|leave|status`, `/setcountry`, `/greeting`

**Admin:** `/admin ban|snapshot|match|resolve|statusreset`

**Owner:** `/owner admin|mmr`

## License

Private. Not open source.
