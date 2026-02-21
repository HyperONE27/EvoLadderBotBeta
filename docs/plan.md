## Problems with the Alpha




## How The Beta Will Be Better




## Beta Planned Feature List



## Beta Architecture Overview

### 1. Discord Bot in Python (discord.py)

Not much should change from the alpha.

Just clean everything into:
- components
- button handlers
- slash command modules should be minimal
- split each admin command into a separate module

Data
- create localization data files
- make sure bot modules use localized strings instead of hardcoded ones
- 

Apparently:
- I was wrong about the 50 API calls/second limit - interaction responses don't count towards the limit
- This means my scaling potential is actually very strong

### 2. Ladder Backend in ~~Go~~ Python

No good replacement for simple columnar operations to Polars

### 3. Replay Parsing Microservice in Python (sc2reader)

- Just port the 


### 4. Remote PowerShell Service for BattleTags

- User calls a remote PowerShell script
- PowerShell script should:
  - Look through all subdirectories under "C:/Users/{stuff}/Documents/StarCraft II/Accounts/..."
  - Gather all toon handles (e.g. "1-S2-...", "2-S2-...", "3-S2-...")
  - 


===

```sql
CREATE TABLE IF NOT EXISTS player_updates (
    id                      SERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL,
    player_name             TEXT NOT NULL,
    setting_name            TEXT NOT NULL,
    old_value               TEXT,
    new_value               TEXT,
    changed_at              TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    changed_by              TEXT DEFAULT 'player' NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_actions (
    id                      SERIAL PRIMARY KEY,
    admin_discord_uid       BIGINT NOT NULL,
    admin_username          TEXT NOT NULL,
    action_type             TEXT NOT NULL,
    target_player_uid       BIGINT,
    target_match_id         INTEGER,
    action_details          JSONB NOT NULL,
    reason                  TEXT,
    performed_at            TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS command_calls (
    id                      SERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL,
    player_name             TEXT NOT NULL,
    command                 TEXT NOT NULL,
    called_at               TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```