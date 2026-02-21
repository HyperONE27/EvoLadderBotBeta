-- =============================================
-- ENUM TYPES
-- =============================================

CREATE TYPE event_type AS ENUM (
    'admin_command',
    'player_command',
    'player_update'
);

CREATE TYPE player_status_type as ENUM (
    'idle',
    'queueing',
    'in_match',
    'timed_out'
);

CREATE TYPE match_mode_type as ENUM (
    '1v1',
    '2v2',
    'FFA'
);

CREATE TYPE player_report_type as ENUM (
    'win',
    'loss',
    'draw',
    'abort',
    'abandoned',
    'no_report'
);

CREATE TYPE match_result_type as ENUM (
    'player_1_win',
    'player_2_win',
    'draw',
    'abort',
    'abandoned',
    'no_report'
);

-- =============================================
-- TABLES
-- =============================================

CREATE TABLE IF NOT EXISTS players (
    id                      SERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL UNIQUE,
    discord_username        TEXT NOT NULL,
    player_name             TEXT,
    alt_player_names        TEXT[],
    battletag               TEXT,
    nationality             TEXT,
    location                TEXT,
    is_banned               BOOLEAN DEFAULT FALSE,
    accepted_tos            BOOLEAN DEFAULT FALSE,
    accepted_tos_at         TIMESTAMPTZ,
    completed_setup         BOOLEAN DEFAULT FALSE,
    completed_setup_at      TIMESTAMPTZ,
    player_status           player_status_type DEFAULT 'idle',
    current_match_mode      match_mode_type DEFAULT NULL,
    current_match_id        INTEGER DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id                      SERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL UNIQUE,
    quick_start_guide       BOOLEAN DEFAULT FALSE,
    shield_battery_bug      BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS events (
    id                      SERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL,
    event_type              event_type NOT NULL,
    event_data              JSONB NOT NULL,
    performed_at            TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS matches_1v1 (
    id                      SERIAL PRIMARY KEY,
    player_1_discord_uid    BIGINT NOT NULL,
    player_2_discord_uid    BIGINT NOT NULL,
    player_1_race           TEXT NOT NULL,
    player_2_race           TEXT NOT NULL,
    player_1_mmr            INTEGER NOT NULL,
    player_2_mmr            INTEGER NOT NULL,
    player_1_report         player_report_type,  -- -4 indicates the player did not confirm the match in time
    player_2_report         player_report_type,  -- -4 indicates the player did not confirm the match in time
    match_result            match_result_type,  -- -1 indicates match was aborted
    mmr_change              INTEGER,
    map_name                TEXT NOT NULL,
    server_name             TEXT NOT NULL,
    assigned_at             TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at            TIMESTAMPTZ DEFAULT NULL,
    player_1_replay_path    TEXT,
    player_1_uploaded_at    TIMESTAMPTZ,
    player_2_replay_path    TEXT,
    player_2_uploaded_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS mmrs_1v1 (
    id                      SERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL,
    player_name             TEXT NOT NULL,
    race                    TEXT NOT NULL,
    mmr                     INTEGER NOT NULL,
    games_played            INTEGER DEFAULT 0,
    games_won               INTEGER DEFAULT 0,
    games_lost              INTEGER DEFAULT 0,
    games_drawn             INTEGER DEFAULT 0,
    last_played_at          TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(discord_uid, race)
);

CREATE TABLE IF NOT EXISTS preferences_1v1 (
    id                      SERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL UNIQUE,
    last_chosen_races       TEXT[],
    last_chosen_vetoes      TEXT[]
);

CREATE TABLE IF NOT EXISTS replays_1v1 (
    id                      SERIAL PRIMARY KEY,
    replay_path             TEXT NOT NULL UNIQUE,
    replay_hash             TEXT NOT NULL,
    replay_time             TIMESTAMPTZ NOT NULL,
    uploaded_at             TIMESTAMPTZ NOT NULL,
    player_1_name           TEXT NOT NULL,
    player_2_name           TEXT NOT NULL,
    player_1_race           TEXT NOT NULL,
    player_2_race           TEXT NOT NULL,
    match_result            match_result_type NOT NULL,
    player_1_handle         TEXT NOT NULL,
    player_2_handle         TEXT NOT NULL,
    observers               TEXT[] NOT NULL DEFAULT '{}',
    map_name                TEXT NOT NULL,
    game_duration           INTEGER NOT NULL,
    game_privacy            TEXT NOT NULL,
    game_speed              TEXT NOT NULL,
    game_duration_setting   TEXT NOT NULL,
    locked_alliances        TEXT NOT NULL,
    cache_handles           TEXT[] NOT NULL
);

/*
-- =============================================
-- "SET IT AND FORGET IT" ANALYTICS FEATURES
-- =============================================

-- These indexes make common queries fast automatically
-- No maintenance required - PostgreSQL handles everything

-- Player lookups (most common operation)
CREATE INDEX IF NOT EXISTS idx_players_discord_uid ON players(discord_uid);
CREATE INDEX IF NOT EXISTS idx_players_username ON players(discord_username);

-- MMR queries (leaderboards, player stats)
CREATE INDEX IF NOT EXISTS idx_mmrs_1v1_discord_uid ON mmrs_1v1(discord_uid);
CREATE INDEX IF NOT EXISTS idx_mmrs_1v1_mmr ON mmrs_1v1(mmr);
CREATE INDEX IF NOT EXISTS idx_mmrs_mmr_lastplayed_id_desc ON mmrs_1v1 (mmr DESC, last_played DESC, id DESC);

-- Match history (player profiles, recent matches)
CREATE INDEX IF NOT EXISTS idx_matches_1v1_player1 ON matches_1v1(player_1_discord_uid);
CREATE INDEX IF NOT EXISTS idx_matches_1v1_player2 ON matches_1v1(player_2_discord_uid);
CREATE INDEX idx_matches_1v1_played_at ON matches_1v1(played_at);

-- Replay lookups (duplicate detection, file management)
CREATE INDEX IF NOT EXISTS idx_replays_hash ON replays_1v1(replay_hash);
CREATE INDEX IF NOT EXISTS idx_replays_date ON replays_1v1(replay_date);

-- Command analytics (usage patterns, debugging)
CREATE INDEX IF NOT EXISTS idx_command_calls_discord_uid ON command_calls(discord_uid);
CREATE INDEX IF NOT EXISTS idx_command_calls_called_at ON command_calls(called_at);
CREATE INDEX IF NOT EXISTS idx_command_calls_command ON command_calls(command);

-- Admin action audit trail (security, compliance)
CREATE INDEX IF NOT EXISTS idx_admin_actions_performed_at ON admin_actions(performed_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_actions_admin ON admin_actions(admin_discord_uid);
CREATE INDEX IF NOT EXISTS idx_admin_actions_target_player ON admin_actions(target_player_uid);
CREATE INDEX IF NOT EXISTS idx_admin_actions_target_match ON admin_actions(target_match_id);
CREATE INDEX IF NOT EXISTS idx_admin_actions_type ON admin_actions(action_type);
*/