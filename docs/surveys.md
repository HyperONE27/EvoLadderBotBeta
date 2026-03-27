# Surveys

Player surveys collect structured feedback at key lifecycle moments. Survey data is **write-only** — responses are persisted to Supabase but never loaded into in-memory DataFrames.

## Survey Types

| Survey | Trigger | Status |
|--------|---------|--------|
| **Setup** | During `/setup`, after notifications step (first-time users only) | Implemented |
| **14-day** | 14 days after first setup | Stub (columns exist, questions TBD) |
| **30-day** | 30 days after first setup | Stub (columns exist, questions TBD) |
| **Post-match** | Probabilistic trigger after match completion | Stub (columns exist, questions TBD) |

## Database Schema

One row per player in the `surveys` table (`discord_uid UNIQUE`). Each survey type has:
- `{prefix}_completed` (BOOLEAN) — whether the survey has been submitted
- `{prefix}_completed_at` (TIMESTAMPTZ) — when it was submitted
- `{prefix}_q{N}_response` (TEXT or TEXT[]) — individual answer slugs

Column prefixes: `setup_`, `d14_`, `d30_`, `post_match_`. The `d14`/`d30` prefixes avoid starting identifiers with a digit (invalid in SQL without quoting).

## Setup Survey Questions

### Q1: "How did you learn about the SC: Evo Complete ladder?"

| Slug | Answer |
|------|--------|
| `friend_or_community` | A friend or community member told me about it directly |
| `live_broadcast` | I watched a live broadcast, live stream, live tournament coverage, etc. |
| `recorded_video` | I watched a recorded video, Video-on-Demand, stream highlight, etc. |
| `evo_discord` | I heard about it in the SC: Evo Complete Discord server after joining for something else |
| `other_discord` | I heard about it elsewhere on Discord |
| `social_media` | I saw it on social media/forums (Reddit, X, TL.net, etc.) |
| `in_game` | I heard about it in-game |
| `other` | Somewhere else |

Single-select. CHECK constraint on column.

### Q2: "How long have you been playing SC: Evo Complete?"

| Slug | Answer |
|------|--------|
| `lt_1mo` | Less than 1 month |
| `1_3mo` | 1–3 months |
| `3_6mo` | 3–6 months |
| `6_12mo` | 6–12 months |
| `gt_1yr` | More than 1 year |

Single-select. CHECK constraint on column.

### Q3: "Which of the following best describes you?"

| Slug | Answer |
|------|--------|
| `casual` | I want to play SC: Evo Complete just occasionally |
| `find_opponents` | I want to consistently find opponents, but don't really care about my skill/rank/MMR |
| `improve_rank` | I am serious about improving and want to track my progress with a real rank/MMR |
| `tournament` | I am actively competing in/preparing to compete in tournaments |
| `avoid_cheaters` | I want to avoid cheaters on the official StarCraft/II ladders |
| `other` | Something else |

Single-select. CHECK constraint on column.

### Q4: "What is your best ladder placement to date on either the Brood War or StarCraft II ladders?"

| Slug | Answer |
|------|--------|
| `no_placement` | I do not have a ladder placement for either game |
| `bw_s` | Brood War, S-Rank |
| `bw_a` | Brood War, A-Rank |
| `bw_b` | Brood War, B-Rank |
| `bw_c` | Brood War, C-Rank or below |
| `sc2_grandmaster` | StarCraft II, Grandmaster League |
| `sc2_master` | StarCraft II, Master League |
| `sc2_diamond` | StarCraft II, Diamond League |
| `sc2_platinum` | StarCraft II, Platinum League or below |

Multi-select (1–2 answers). Stored as `TEXT[]` with `<@` containment CHECK. Application-layer validation enforces:
- `no_placement` cannot be combined with any other option
- At most one Brood War answer and one StarCraft II answer

## API

| Method | Endpoint | Purpose |
|--------|----------|---------|
| PUT | `/surveys/setup` | Persist setup survey responses (returns 204) |

Future endpoints: `PUT /surveys/d14`, `PUT /surveys/d30`, `PUT /surveys/post-match`.

## Bot Integration

The survey step appears in the `/setup` flow **only for first-time users** (`completed_setup = false` in the players table). Returning players who re-run `/setup` skip the survey and go directly from notifications to preview.

The Discord UI uses 5 rows: 4 Select menus (one per question) on rows 0–3 and Confirm/Restart/Cancel buttons on row 4. This is the Discord maximum.

Q1–Q3 options display numbered emoji (1️⃣–8️⃣). Q4 options display rank emotes (U/S/A/B/C) for Brood War and league emotes (Grandmaster/Master/Diamond/Platinum) for StarCraft II.

## Adding Future Survey Questions

1. Define questions, answer text, and slug values
2. Add CHECK constraints to the stub columns in `schema.sql`
3. Add a `DatabaseWriter.upsert_{type}_survey()` method
4. Add `TransitionManager.save_{type}_survey()` inline method
5. Add `Orchestrator.save_{type}_survey()` delegation
6. Add `PUT /surveys/{type}` endpoint + Pydantic request model
7. Add i18n keys to all 6 locale files (lexicographic order)
8. Build the bot view/embed and wire the trigger
