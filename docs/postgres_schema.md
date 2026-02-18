```sql
-- =============================================
-- CORE TABLES (PostgreSQL with timezone-aware timestamps)
-- =============================================
-- NOTE: All timestamp columns use TIMESTAMPTZ to store UTC timestamps
-- with timezone information. This ensures proper handling across timezones.

CREATE TABLE players (
    id                      SERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL UNIQUE,
    discord_username        TEXT NOT NULL,
    player_name             TEXT,
    battletag               TEXT,
    alt_player_name_1       TEXT,
    alt_player_name_2       TEXT,
    country                 TEXT,
    region                  TEXT,
    accepted_tos            BOOLEAN DEFAULT FALSE,
    accepted_tos_date       TIMESTAMPTZ,
    completed_setup         BOOLEAN DEFAULT FALSE,
    completed_setup_date    TIMESTAMPTZ,
    activation_code         TEXT,
    created_at              TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    remaining_aborts        INTEGER DEFAULT 3,
    player_state            TEXT DEFAULT 'idle',
    shield_battery_bug      BOOLEAN DEFAULT FALSE,
    is_banned               BOOLEAN DEFAULT FALSE,
    read_quick_start_guide  BOOLEAN DEFAULT FALSE
);

CREATE TABLE player_action_logs (
    id                      SERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL,
    player_name             TEXT NOT NULL,
    setting_name            TEXT NOT NULL,
    old_value               TEXT,
    new_value               TEXT,
    changed_at              TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    changed_by              TEXT DEFAULT 'player' NOT NULL
);

CREATE TABLE command_calls (
    id                      SERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL,
    player_name             TEXT NOT NULL,
    command                 TEXT NOT NULL,
    called_at               TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE replays (
    id                      SERIAL PRIMARY KEY,
    replay_path             TEXT NOT NULL UNIQUE,
    replay_hash             TEXT NOT NULL,
    replay_date             TIMESTAMPTZ NOT NULL,
    player_1_name           TEXT NOT NULL,
    player_2_name           TEXT NOT NULL,
    player_1_race           TEXT NOT NULL,
    player_2_race           TEXT NOT NULL,
    result                  INTEGER NOT NULL,
    player_1_handle         TEXT NOT NULL,
    player_2_handle         TEXT NOT NULL,
    observers               TEXT NOT NULL,
    map_name                TEXT NOT NULL,
    duration                INTEGER NOT NULL,
    uploaded_at             TIMESTAMPTZ NOT NULL,
    game_privacy            TEXT NOT NULL,
    game_speed              TEXT NOT NULL,
    game_duration_setting   TEXT NOT NULL,
    locked_alliances        TEXT NOT NULL,
    cache_handles           TEXT NOT NULL             -- NEW: JSON array of mod cache handle URLs
);

CREATE TABLE mmrs_1v1 (
    id                      SERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL,
    player_name             TEXT NOT NULL,
    race                    TEXT NOT NULL,
    mmr                     INTEGER NOT NULL,
    games_played            INTEGER DEFAULT 0,
    games_won               INTEGER DEFAULT 0,
    games_lost              INTEGER DEFAULT 0,
    games_drawn             INTEGER DEFAULT 0,
    last_played             TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(discord_uid, race)
);

CREATE TABLE matches_1v1 (
    id                      SERIAL PRIMARY KEY,
    player_1_discord_uid    BIGINT NOT NULL,
    player_2_discord_uid    BIGINT NOT NULL,
    player_1_race           TEXT NOT NULL,
    player_2_race           TEXT NOT NULL,
    player_1_mmr            INTEGER NOT NULL,
    player_2_mmr            INTEGER NOT NULL,
    player_1_report         INTEGER,  -- -4 indicates the player did not confirm the match in time
    player_2_report         INTEGER,  -- -4 indicates the player did not confirm the match in time
    match_result            INTEGER,  -- -1 indicates match was aborted
    mmr_change              INTEGER,
    map_played              TEXT NOT NULL,
    server_used             TEXT NOT NULL,
    played_at               TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    player_1_replay_path    TEXT,
    player_1_replay_time    TIMESTAMPTZ,
    player_2_replay_path    TEXT,
    player_2_replay_time    TIMESTAMPTZ
);

CREATE TABLE preferences_1v1 (
    id                      SERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL UNIQUE,
    last_chosen_races       TEXT,
    last_chosen_vetoes      TEXT
);

CREATE TABLE admin_actions (
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

-- =============================================
-- "SET IT AND FORGET IT" ANALYTICS FEATURES
-- =============================================

-- These indexes make common queries fast automatically
-- No maintenance required - PostgreSQL handles everything

-- Player lookups (most common operation)
CREATE INDEX idx_players_discord_uid ON players(discord_uid);
CREATE INDEX idx_players_username ON players(discord_username);

-- MMR queries (leaderboards, player stats)
CREATE INDEX idx_mmrs_1v1_discord_uid ON mmrs_1v1(discord_uid);
CREATE INDEX idx_mmrs_1v1_mmr ON mmrs_1v1(mmr);
CREATE INDEX idx_mmrs_mmr_lastplayed_id_desc ON mmrs_1v1 (mmr DESC, last_played DESC, id DESC);

-- Match history (player profiles, recent matches)
CREATE INDEX idx_matches_1v1_player1 ON matches_1v1(player_1_discord_uid);
CREATE INDEX idx_matches_1v1_player2 ON matches_1v1(player_2_discord_uid);
CREATE INDEX idx_matches_1v1_played_at ON matches_1v1(played_at);

-- Replay lookups (duplicate detection, file management)
CREATE INDEX idx_replays_hash ON replays(replay_hash);
CREATE INDEX idx_replays_date ON replays(replay_date);

-- Command analytics (usage patterns, debugging)
CREATE INDEX idx_command_calls_discord_uid ON command_calls(discord_uid);
CREATE INDEX idx_command_calls_called_at ON command_calls(called_at);
CREATE INDEX idx_command_calls_command ON command_calls(command);

-- Admin action audit trail (security, compliance)
CREATE INDEX idx_admin_actions_performed_at ON admin_actions(performed_at DESC);
CREATE INDEX idx_admin_actions_admin ON admin_actions(admin_discord_uid);
CREATE INDEX idx_admin_actions_target_player ON admin_actions(target_player_uid);
CREATE INDEX idx_admin_actions_target_match ON admin_actions(target_match_id);
CREATE INDEX idx_admin_actions_type ON admin_actions(action_type);