# EvoLadderBotBeta

Discord ladder (ranked matchmaking) for **SC: Evo Complete** — a StarCraft II mod. Players use slash commands and DMs to register, queue, confirm matches, upload replays, and climb 1v1 / 2v2 leaderboards. Game state is authoritative on a FastAPI backend (in-memory [Polars](https://pola.rs/) over Supabase/PostgreSQL); the Discord bot is a thin client over HTTP and WebSocket.

## Documentation

**[CLAUDE.md](./CLAUDE.md)** is the canonical reference for architecture, processes, environment variables, data flows, naming conventions, and contribution guardrails. Start there for anything beyond this README.

Additional docs:

- [docs/testing.md](./docs/testing.md) — why automated tests focus on pure algorithms (invariants, not fixed numeric outcomes)
- [docs/TODO_beta_clean.md](./docs/TODO_beta_clean.md) — beta backlog and gaps (e.g. 2v2 admin tooling, planned modes)

## Repository layout

| Path | Role |
|------|------|
| `backend/` | FastAPI API, orchestration, matchmakers, replay pipeline, WebSocket hub |
| `bot/` | `discord.py` application: commands, embeds, views, backend HTTP client, WS listener |
| `channel_manager/` | Optional microservice: create/delete match channels via Discord REST (+ gateway for logging) |
| `common/` | Shared types, i18n, JSON/datetime helpers — used by backend and bot |
| `data/core/` | Static game JSON (maps, races, regions, …) |
| `data/locales/` | Locale strings (`common/i18n.t`) |
| `tests/` | Pytest suite for ratings, Hungarian assignment, matchmakers, match params |
| `backend/database/schema.sql` | PostgreSQL schema for Supabase |

## Requirements

- **Python 3.14** (see [`runtime.txt`](./runtime.txt))
- Supabase project (PostgreSQL + Storage bucket for replays)
- Discord application / bot token(s)

## Quick start (local)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # ruff, mypy — needed for `make quality`
```

Create a **`.env`** in the project root. Variable names and semantics are listed in [CLAUDE.md § Environment Variables](./CLAUDE.md#environment-variables) (backend, bot, and channel manager each need their own subset).

**Local URLs** (see [`run_local.sh`](./run_local.sh)):

- Backend: `http://127.0.0.1:8080`
- Channel manager: `http://127.0.0.1:8090`

Point the bot at the backend (e.g. `BACKEND_URL=http://127.0.0.1:8080`). If you want match channels created locally, set `CHANNEL_MANAGER_URL=http://127.0.0.1:8090` on the backend; if unset, channel creation is skipped.

Run all three processes:

```bash
make run
# or: ./run_local.sh
```

## Quality and tests

```bash
make quality    # ruff check --fix, ruff format, mypy backend bot channel_manager common
python -m pytest tests/ -v
```

CI (`.github/workflows/ci.yml`) runs on pushes and PRs to `main`: `ruff` (check + format check) and `mypy` on Python 3.14.

## Deployment

Production is set up for **[Railway](https://railway.app/)** as three services, each with a `railway.json` defining the start command:

- `backend/` — `uvicorn backend.api.app:app` with **`--workers 1`** (required: single in-memory state)
- `bot/` — `python -m bot.core.app`
- `channel_manager/` — `python -m channel_manager.app`

Configure the same environment variables as in production `.env`; see CLAUDE.md.

## License

No `LICENSE` file is present in this repository. Add one if you intend to open-source or redistribute.
