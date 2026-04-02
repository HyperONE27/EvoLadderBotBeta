-- =============================================
-- TABLES
-- =============================================

CREATE TABLE IF NOT EXISTS admins (
    id                      SMALLSERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL UNIQUE,
    discord_username        TEXT NOT NULL,
    role                    TEXT NOT NULL DEFAULT 'admin'
        CHECK (role IN
            ('owner', 'admin', 'inactive')
        ),
    first_promoted_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_promoted_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_demoted_at         TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS players (
    id                      BIGSERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL UNIQUE,
    discord_username        TEXT NOT NULL,
    player_name             TEXT,       -- 3-12 letters
    alt_player_names        TEXT[],
    battletag               TEXT,       -- 1-12 letters + "#" + 3-5 digits
    nationality             TEXT,       -- ISO 3166-1 alpha-2 code
    location                TEXT,       -- regions.json geographic region code
    language                TEXT NOT NULL DEFAULT 'enUS'
        CHECK (language IN
            ('enUS', 'esMX', 'koKR', 'ruRU', 'zhCN')
        ),
    is_banned               BOOLEAN NOT NULL DEFAULT FALSE,
    accepted_tos            BOOLEAN NOT NULL DEFAULT FALSE,
    accepted_tos_at         TIMESTAMPTZ,
    completed_setup         BOOLEAN NOT NULL DEFAULT FALSE,
    completed_setup_at      TIMESTAMPTZ,
    player_status           TEXT NOT NULL DEFAULT 'idle'
        CHECK (player_status IN
            ('idle', 'queueing', 'in_match', 'timed_out', 'in_party')
        ),
    current_match_mode      TEXT DEFAULT NULL
        CHECK (current_match_mode IN 
            ('1v1', '2v2', 'FFA')
        ),
    current_match_id        BIGINT DEFAULT NULL,
    read_lobby_guide        BOOLEAN NOT NULL DEFAULT FALSE,
    referred_by             BIGINT,
    referred_at             TIMESTAMPTZ,    -- this value is set to Unix epoch zero for players who joined before pre-beta referral system
    timeout_until           TIMESTAMPTZ DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id                              BIGSERIAL PRIMARY KEY,
    discord_uid                     BIGINT NOT NULL UNIQUE,
    read_quick_start_guide          BOOLEAN NOT NULL DEFAULT FALSE,

    -- Queue activity pings (/notifyme). One flag per ladder mode (2v2/FFA stubbed).
    -- Per-mode cooldown (minutes) between anonymous “someone is queueing” DMs.
    -- Defaults match QUEUE_NOTIFY_COOLDOWN_MINUTES_DEFAULT in common/config.py.
    notify_queue_1v1                BOOLEAN NOT NULL DEFAULT FALSE,
    notify_queue_1v1_cooldown       SMALLINT NOT NULL DEFAULT 15
        CHECK (notify_queue_1v1_cooldown >= 5 AND notify_queue_1v1_cooldown <= 1440),
    notify_queue_1v1_last_sent      TIMESTAMPTZ,
    notify_queue_2v2                BOOLEAN NOT NULL DEFAULT FALSE,
    notify_queue_2v2_cooldown       SMALLINT NOT NULL DEFAULT 15
        CHECK (notify_queue_2v2_cooldown >= 5 AND notify_queue_2v2_cooldown <= 1440),
    notify_queue_2v2_last_sent      TIMESTAMPTZ,
    notify_queue_ffa                BOOLEAN NOT NULL DEFAULT FALSE,
    notify_queue_ffa_cooldown       SMALLINT NOT NULL DEFAULT 15
        CHECK (notify_queue_ffa_cooldown >= 5 AND notify_queue_ffa_cooldown <= 1440),
    notify_queue_ffa_last_sent      TIMESTAMPTZ,
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- probably don't need these if writes are infrequent and reads are done in Polars
-- CREATE INDEX IF NOT EXISTS idx_notifications_notify_1v1
--     ON notifications (notify_queue_1v1)
--     WHERE notify_queue_1v1 = TRUE;
-- CREATE INDEX IF NOT EXISTS idx_notifications_notify_2v2
--     ON notifications (notify_queue_2v2)
--     WHERE notify_queue_2v2 = TRUE;
-- CREATE INDEX IF NOT EXISTS idx_notifications_notify_ffa
--     ON notifications (notify_queue_ffa)
--     WHERE notify_queue_ffa = TRUE;

CREATE TABLE IF NOT EXISTS events (
    id                      BIGSERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL,
        -- Acting user UID.  Sentinels: 1 = backend process, 2 = bot process.
    event_type              TEXT NOT NULL
        CHECK (event_type IN (
            'player_command', 'admin_command', 'owner_command',
            'player_update',  'match_event',   'system_event'
        )),
    action                  TEXT NOT NULL,
        -- Specific sub-type, e.g. "setup", "ban", "match_found", "matchmaking_wave"
    game_mode               TEXT
        CHECK (game_mode IN ('1v1', '2v2', 'FFA') OR game_mode IS NULL),
        -- Populated for queue/match events; NULL otherwise
    match_id                BIGINT,
        -- Populated for match_event rows and match-related commands
    target_discord_uid      BIGINT,
        -- Populated for admin/owner actions that target another player
    event_data              JSONB NOT NULL,
        -- Full serialised payload (arguments, before/after values, etc.)
    performed_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common query patterns
-- CREATE INDEX IF NOT EXISTS idx_events_discord_uid  ON events(discord_uid);
-- CREATE INDEX IF NOT EXISTS idx_events_match_id     ON events(match_id);
-- CREATE INDEX IF NOT EXISTS idx_events_target_uid   ON events(target_discord_uid);
-- CREATE INDEX IF NOT EXISTS idx_events_action       ON events(action);
-- CREATE INDEX IF NOT EXISTS idx_events_event_type   ON events(event_type);
-- CREATE INDEX IF NOT EXISTS idx_events_performed_at ON events(performed_at DESC);

CREATE TABLE IF NOT EXISTS surveys (
    id                          BIGSERIAL PRIMARY KEY,
    discord_uid                 BIGINT NOT NULL UNIQUE,

    -- Setup survey (asked during /setup for first-time users only)
    setup_completed             BOOLEAN NOT NULL DEFAULT FALSE,
    setup_completed_at          TIMESTAMPTZ,

    -- Q1: "How did you learn about the SC: Evo Complete ladder?"
    setup_q1_response           TEXT
        CHECK (setup_q1_response IN (
            'friend_or_community',  'live_broadcast',
            'recorded_video',       'evo_discord',
            'other_discord',        'social_media',
            'in_game',              'other'
        )),
    -- Q2: "How long have you been playing SC: Evo Complete?"
    setup_q2_response           TEXT
        CHECK (setup_q2_response IN (
            'lt_1mo', '1_3mo', '3_6mo', '6_12mo', 'gt_1yr'
        )),
    -- Q3: "Which of the following best describes you?"
    setup_q3_response           TEXT
        CHECK (setup_q3_response IN (
            'casual',       'find_opponents',
            'improve_rank', 'tournament',
            'avoid_cheaters', 'other'
        )),
    -- Q4: "Best ladder placement (BW / SC2)?" — 1-2 selections, max 1 per game
    setup_q4_response           TEXT[]
        CHECK (setup_q4_response <@ ARRAY[
            'no_placement',
            'bw_s', 'bw_a', 'bw_b', 'bw_c',
            'sc2_grandmaster', 'sc2_master', 'sc2_diamond', 'sc2_platinum'
        ]::text[]),

    -- 14-day survey (stub — questions TBD)
    d14_completed               BOOLEAN NOT NULL DEFAULT FALSE,
    d14_completed_at            TIMESTAMPTZ,
    d14_q1_response             TEXT,
    d14_q2_response             TEXT,
    d14_q3_response             TEXT,
    d14_q4_response             TEXT,

    -- 30-day survey (stub — questions TBD)
    d30_completed               BOOLEAN NOT NULL DEFAULT FALSE,
    d30_completed_at            TIMESTAMPTZ,
    d30_q1_response             TEXT,
    d30_q2_response             TEXT,
    d30_q3_response             TEXT,
    d30_q4_response             TEXT,

    -- Post-match survey (stub — one per player for now; questions TBD)
    post_match_completed        BOOLEAN NOT NULL DEFAULT FALSE,
    post_match_completed_at     TIMESTAMPTZ,
    post_match_q1_response      TEXT,
    post_match_q2_response      TEXT,
    post_match_q3_response      TEXT,
    post_match_q4_response      TEXT,

    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS matches_1v1 (
    id                      BIGSERIAL PRIMARY KEY,
    player_1_discord_uid    BIGINT NOT NULL,
    player_2_discord_uid    BIGINT NOT NULL,
    player_1_name           TEXT NOT NULL,
    player_2_name           TEXT NOT NULL,
    player_1_race           TEXT NOT NULL,
        CHECK (player_1_race IN
            ('bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss')
        ),
    player_2_race           TEXT NOT NULL,
        CHECK (player_2_race IN
            ('bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss')
        ),
    player_1_mmr            SMALLINT NOT NULL,
    player_2_mmr            SMALLINT NOT NULL,
    player_1_report         TEXT
        CHECK (player_1_report IN 
            ('player_1_win', 'player_2_win', 'draw', 
            'abort', 'abandoned', 'invalidated', 'no_report')
        ),
    player_2_report         TEXT
        CHECK (player_2_report IN 
            ('player_1_win', 'player_2_win', 'draw', 
            'abort', 'abandoned', 'invalidated', 'no_report')
        ),
    match_result            TEXT
        CHECK (match_result IN 
            ('player_1_win', 'player_2_win', 'draw', 'conflict', 
            'abort', 'abandoned', 'invalidated', 'no_report')
        ),
    player_1_mmr_change     SMALLINT,
    player_2_mmr_change     SMALLINT,
    map_name                TEXT NOT NULL,
    server_name             TEXT NOT NULL,
    assigned_at             TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,
    admin_intervened        BOOLEAN NOT NULL DEFAULT FALSE,
    admin_discord_uid       BIGINT DEFAULT NULL,
    player_1_replay_path    TEXT,
    player_1_replay_row_id  BIGINT,
    player_1_uploaded_at    TIMESTAMPTZ,
    player_2_replay_path    TEXT,
    player_2_replay_row_id  BIGINT,
    player_2_uploaded_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS mmrs_1v1 (
    id                      BIGSERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL,
    player_name             TEXT NOT NULL,
    race                    TEXT NOT NULL,
        CHECK (race IN
            ('bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss')
        ),
    mmr                     SMALLINT NOT NULL,
    games_played            INTEGER NOT NULL DEFAULT 0,
    games_won               INTEGER NOT NULL DEFAULT 0,
    games_lost              INTEGER NOT NULL DEFAULT 0,
    games_drawn             INTEGER NOT NULL DEFAULT 0,
    last_played_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(discord_uid, race)
);

CREATE TABLE IF NOT EXISTS preferences_1v1 (
    id                      BIGSERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL UNIQUE,
    last_chosen_races       TEXT[],
    last_chosen_vetoes      TEXT[]
);

CREATE TABLE IF NOT EXISTS replays_1v1 (
    id                      BIGSERIAL PRIMARY KEY,
    matches_1v1_id          BIGINT NOT NULL,
    replay_path             TEXT NOT NULL UNIQUE,
    replay_hash             TEXT NOT NULL,
    replay_time             TIMESTAMPTZ NOT NULL,
    uploaded_at             TIMESTAMPTZ NOT NULL,
    player_1_name           TEXT NOT NULL,
    player_2_name           TEXT NOT NULL,
    player_1_race           TEXT NOT NULL,
        CHECK (player_1_race IN
            ('bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss')
        ),
    player_2_race           TEXT NOT NULL,
        CHECK (player_2_race IN
            ('bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss')
        ),
    match_result            TEXT NOT NULL
        CHECK (match_result IN 
            ('player_1_win', 'player_2_win', 'draw')
        ),
    player_1_handle         TEXT NOT NULL,
    player_2_handle         TEXT NOT NULL,
    observers               TEXT[] NOT NULL DEFAULT '{}',
    map_name                TEXT NOT NULL,
    game_duration_seconds   INTEGER NOT NULL,
    game_privacy            TEXT NOT NULL,
    game_speed              TEXT NOT NULL,
    game_duration_setting   TEXT NOT NULL,
    locked_alliances        TEXT NOT NULL,
    cache_handles           TEXT[] NOT NULL,
    upload_status           TEXT NOT NULL
        CHECK (upload_status IN 
            ('pending', 'completed', 'failed')
        )
);

CREATE TABLE IF NOT EXISTS matches_2v2 (
    id                          BIGSERIAL PRIMARY KEY,

    -- Team 1
    team_1_player_1_discord_uid         BIGINT NOT NULL,
    team_1_player_2_discord_uid         BIGINT NOT NULL,
    team_1_player_1_name        TEXT NOT NULL,
    team_1_player_2_name        TEXT NOT NULL,
    team_1_player_1_race        TEXT NOT NULL
        CHECK (team_1_player_1_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    team_1_player_2_race        TEXT NOT NULL
        CHECK (team_1_player_2_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    team_1_mmr                  SMALLINT NOT NULL,

    -- Team 2
    team_2_player_1_discord_uid         BIGINT NOT NULL,
    team_2_player_2_discord_uid         BIGINT NOT NULL,
    team_2_player_1_name        TEXT NOT NULL,
    team_2_player_2_name        TEXT NOT NULL,
    team_2_player_1_race        TEXT NOT NULL
        CHECK (team_2_player_1_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    team_2_player_2_race        TEXT NOT NULL
        CHECK (team_2_player_2_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    team_2_mmr                  SMALLINT NOT NULL,

    -- Reporting (one per team; either member may submit)
    team_1_reporter_discord_uid         BIGINT,
    team_1_report               TEXT
        CHECK (team_1_report IN (
            'team_1_win', 'team_2_win', 'draw',
            'abort', 'abandoned', 'invalidated', 'no_report'
        )),
    team_2_reporter_discord_uid         BIGINT,
    team_2_report               TEXT
        CHECK (team_2_report IN (
            'team_1_win', 'team_2_win', 'draw',
            'abort', 'abandoned', 'invalidated', 'no_report'
        )),

    -- Resolution
    match_result                TEXT
        CHECK (match_result IN (
            'team_1_win', 'team_2_win', 'draw', 'conflict',
            'abort', 'abandoned', 'invalidated', 'no_report'
        )),
    team_1_mmr_change           SMALLINT,
    team_2_mmr_change           SMALLINT,

    -- Map / server
    map_name                    TEXT NOT NULL,
    server_name                 TEXT NOT NULL,

    -- Timestamps
    assigned_at                 TIMESTAMPTZ,
    completed_at                TIMESTAMPTZ,

    -- Admin
    admin_intervened            BOOLEAN NOT NULL DEFAULT FALSE,
    admin_discord_uid           BIGINT DEFAULT NULL,

    -- Replays (one upload slot per team)
    team_1_replay_path          TEXT,
    team_1_replay_row_id        BIGINT,
    team_1_uploaded_at          TIMESTAMPTZ,
    team_2_replay_path          TEXT,
    team_2_replay_row_id        BIGINT,
    team_2_uploaded_at          TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS mmrs_2v2 (
    id                      BIGSERIAL PRIMARY KEY,
    player_1_discord_uid    BIGINT NOT NULL,   -- smaller of the two UIDs (normalized)
    player_2_discord_uid    BIGINT NOT NULL,   -- larger of the two UIDs (normalized)
    player_1_name           TEXT NOT NULL,
    player_2_name           TEXT NOT NULL,
    mmr                     SMALLINT NOT NULL,
    games_played            INTEGER NOT NULL DEFAULT 0,
    games_won               INTEGER NOT NULL DEFAULT 0,
    games_lost              INTEGER NOT NULL DEFAULT 0,
    games_drawn             INTEGER NOT NULL DEFAULT 0,
    last_played_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (player_1_discord_uid, player_2_discord_uid)
);

CREATE TABLE IF NOT EXISTS preferences_2v2 (
    id                        BIGSERIAL PRIMARY KEY,
    discord_uid               BIGINT NOT NULL UNIQUE,
    last_pure_bw_leader_race  TEXT,
    last_pure_bw_member_race  TEXT,
    last_mixed_leader_race    TEXT,
    last_mixed_member_race    TEXT,
    last_pure_sc2_leader_race TEXT,
    last_pure_sc2_member_race TEXT,
    last_chosen_vetoes        TEXT[]
);

CREATE TABLE IF NOT EXISTS replays_2v2 (
    id                          BIGSERIAL PRIMARY KEY,
    matches_2v2_id              BIGINT NOT NULL,
    replay_path                 TEXT NOT NULL UNIQUE,
    replay_hash                 TEXT NOT NULL,
    replay_time                 TIMESTAMPTZ NOT NULL,
    uploaded_at                 TIMESTAMPTZ NOT NULL,
    -- Four players (team_1_p1, team_1_p2, team_2_p1, team_2_p2)
    team_1_player_1_name        TEXT NOT NULL,
    team_1_player_2_name        TEXT NOT NULL,
    team_2_player_1_name        TEXT NOT NULL,
    team_2_player_2_name        TEXT NOT NULL,
    team_1_player_1_race        TEXT NOT NULL
        CHECK (team_1_player_1_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    team_1_player_2_race        TEXT NOT NULL
        CHECK (team_1_player_2_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    team_2_player_1_race        TEXT NOT NULL
        CHECK (team_2_player_1_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    team_2_player_2_race        TEXT NOT NULL
        CHECK (team_2_player_2_race IN (
            'bw_terran', 'bw_zerg', 'bw_protoss',
            'sc2_terran', 'sc2_zerg', 'sc2_protoss'
        )),
    match_result                TEXT NOT NULL
        CHECK (match_result IN ('team_1_win', 'team_2_win', 'draw', 'indeterminate')),
    -- sc2reader toon handles (all four players)
    team_1_player_1_handle      TEXT NOT NULL,
    team_1_player_2_handle      TEXT NOT NULL,
    team_2_player_1_handle      TEXT NOT NULL,
    team_2_player_2_handle      TEXT NOT NULL,
    observers                   TEXT[] NOT NULL DEFAULT '{}',
    map_name                    TEXT NOT NULL,
    game_duration_seconds       INTEGER NOT NULL,
    game_privacy                TEXT NOT NULL,
    game_speed                  TEXT NOT NULL,
    game_duration_setting       TEXT NOT NULL,
    locked_alliances            TEXT NOT NULL,
    cache_handles               TEXT[] NOT NULL,
    upload_status               TEXT NOT NULL
        CHECK (upload_status IN ('pending', 'completed', 'failed'))
);

-- Below are indexes I don't really think I care about right now

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