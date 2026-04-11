-- =============================================
-- Channel Manager — Supabase table definition
-- =============================================
-- Hosted in the same Supabase project as the backend tables.
-- Run once against the project to create the table.

CREATE TABLE IF NOT EXISTS channels (
    id              BIGSERIAL PRIMARY KEY,
    match_id        BIGINT NOT NULL,
    match_mode      TEXT NOT NULL
                        CHECK (match_mode IN ('1v1', '2v2', 'FFA')),
    channel_id      BIGINT NOT NULL UNIQUE,   -- Discord channel snowflake
    message_id      BIGINT,                    -- snowflake of the welcome ping message (NULL if the message send failed)
    message_url     TEXT,                      -- https://discord.com/channels/{guild}/{channel}/{message} (NULL if no welcome message)
    messages        JSONB NOT NULL DEFAULT '[]',
        -- Append-only log of messages and edits for audit purposes.
        -- Message entry: {"type": "message", "message_id": <int>, "ts": "<ISO>", "discord_uid": <int>, "content": "<text>"}
        -- Edit entry:    {"type": "edit",    "message_id": <int>, "ts": "<ISO>", "discord_uid": <int>, "original_content": "<text>", "new_content": "<text>"}
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at      TIMESTAMPTZ,              -- NULL until the channel is deleted

    -- Composite uniqueness: the same match_id integer can appear in different game modes
    -- (matches_1v1 and matches_2v2 use independent sequences).
    CONSTRAINT uq_channels_match_id_mode UNIQUE (match_id, match_mode)
);

-- Idempotent migration: relax NOT NULL on the welcome message columns so that
-- channel creation can record the row even when the initial ping send fails
-- transiently (Discord 5xx). Safe to re-run.
ALTER TABLE channels ALTER COLUMN message_id  DROP NOT NULL;
ALTER TABLE channels ALTER COLUMN message_url DROP NOT NULL;

-- Atomically appends one message entry to the messages JSONB array.
CREATE OR REPLACE FUNCTION append_channel_message(
    p_channel_id BIGINT,
    p_message    JSONB
) RETURNS VOID LANGUAGE SQL AS $$
    UPDATE channels
    SET messages = messages || jsonb_build_array(p_message)
    WHERE channel_id = p_channel_id;
$$;