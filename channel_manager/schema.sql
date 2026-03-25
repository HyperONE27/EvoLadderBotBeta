-- =============================================
-- Channel Manager — Supabase table definition
-- =============================================
-- Hosted in the same Supabase project as the backend tables.
-- Run once against the project to create the table.

CREATE TABLE IF NOT EXISTS channels (
    id              BIGSERIAL PRIMARY KEY,
    match_id        BIGINT NOT NULL UNIQUE,
    match_mode      TEXT NOT NULL
                        CHECK (match_mode IN ('1v1', '2v2', 'FFA')),
    channel_id      BIGINT NOT NULL UNIQUE,   -- Discord channel snowflake
    message_id      BIGINT NOT NULL,           -- snowflake of the ping message in the channel
    message_url     TEXT NOT NULL,             -- https://discord.com/channels/{guild}/{channel}/{message}
    messages        JSONB NOT NULL DEFAULT '[]',
        -- Append-only log of messages sent in the channel for audit purposes.
        -- Each entry: {"ts": "<ISO timestamp>", "discord_uid": <int>, "content": "<text>"}
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at      TIMESTAMPTZ               -- NULL until the channel is deleted
);

CREATE INDEX IF NOT EXISTS idx_channels_match_id ON channels (match_id);

-- Atomically appends one message entry to the messages JSONB array.
CREATE OR REPLACE FUNCTION append_channel_message(
    p_channel_id BIGINT,
    p_message    JSONB
) RETURNS VOID LANGUAGE SQL AS $$
    UPDATE channels
    SET messages = messages || jsonb_build_array(p_message)
    WHERE channel_id = p_channel_id;
$$;
