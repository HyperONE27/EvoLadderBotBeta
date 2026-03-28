# Events Table Reference

The `events` table is a **write-only audit log**. Every user action, admin command, match lifecycle transition, and system operation that mutates state (or is worth tracking) inserts a row. The table is never read by application code — it exists for analytics, debugging, and post-hoc analysis via direct SQL.

Failures in `insert_event()` are logged with structlog but **never propagated** — event logging is non-critical and must not break the operation that triggered it.

## Schema

```sql
CREATE TABLE IF NOT EXISTS events (
    id                      BIGSERIAL PRIMARY KEY,
    discord_uid             BIGINT NOT NULL,
    event_type              TEXT NOT NULL
        CHECK (event_type IN (
            'player_command', 'admin_command', 'owner_command',
            'player_update',  'match_event',   'system_event'
        )),
    action                  TEXT NOT NULL,
    game_mode               TEXT
        CHECK (game_mode IN ('1v1', '2v2', 'FFA') OR game_mode IS NULL),
    match_id                BIGINT,
    target_discord_uid      BIGINT,
    event_data              JSONB NOT NULL,
    performed_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Python TypedDict: `backend/domain_types/events.py` — `EventRow`.

Required fields: `discord_uid`, `event_type`, `action`, `event_data`.
Optional (default NULL): `game_mode`, `match_id`, `target_discord_uid`.

## Write path

```
caller  →  TransitionManager.log_event(row)      [backend/orchestrator/transitions/__init__.py:117]
            └─ DatabaseWriter.insert_event(row)   [backend/database/database.py:800]
                 └─ _serialise_event_row(row)      (datetime → ISO string)
                 └─ supabase .table("events").insert(…)
```

Some call sites bypass `log_event()` and call `_db_writer.insert_event()` directly (transition modules). The behaviour is identical.

## Sentinel UIDs

| `discord_uid` | Meaning |
|---|---|
| `1` | Backend process (matchmaking waves, timeouts, auto-resolutions) |
| `2` | Bot process (guild member join forwarded from discord.py) |
| Any other value | Actual Discord user UID |

---

## `player_command`

User-initiated commands and actions. `discord_uid` is the acting player.

| Action | Trigger | Endpoint / Method | `game_mode` | `match_id` | `event_data` keys |
|---|---|---|---|---|---|
| `greeting` | `/greeting` command | `GET /commands/greet/{uid}` | — | — | *(empty)* |
| `first_setup_started` | First-time user opens `/setup` | `POST /events/first_setup_started` | — | — | `discord_username` |
| `first_setup_completed` | First-time user completes `/setup` | `PUT /commands/setup` | — | — | `player_name`, `battletag`, `nationality`, `location`, `language`, `notify_queue_1v1`, `notify_queue_1v1_cooldown`, `notify_queue_2v2`, `notify_queue_2v2_cooldown` |
| `setup` | `/setup` completion | `PUT /commands/setup` | — | — | `player_name`, `battletag`, `nationality`, `location`, `language`, `notify_queue_1v1`, `notify_queue_1v1_cooldown`, `notify_queue_2v2`, `notify_queue_2v2_cooldown` |
| `termsofservice` | ToS accept/decline | `PUT /commands/termsofservice` | — | — | `accepted` |
| `setcountry` | `/setcountry` command | `PUT /commands/setcountry` | — | — | `country_code` |
| `setup_survey_submitted` | Setup survey answers | `TransitionManager.save_setup_survey()` | — | — | `setup_q1_response`, `setup_q2_response`, `setup_q3_response`, `setup_q4_response` |
| `referral_pitch_generated` | Player generates referral embed | `TransitionManager.log_referral_pitch()` | — | — | `referral_code` |
| `referral_submission` *(failure)* | Referral validation fails | `_player.submit_referral()` | — | — | `status` (`"failure"`), `error`, `referral_code`; `target_discord_uid` set if referrer found |
| `queue_join` | Join 1v1 queue | `POST /queue_1v1/join` | `1v1` | — | `bw_race`, `sc2_race`, `bw_mmr`, `sc2_mmr`, `map_vetoes` |
| `queue_join` | Join 2v2 queue | `POST /queue_2v2/join` | `2v2` | — | `pure_bw_leader_race`, `pure_bw_member_race`, `mixed_leader_race`, `mixed_member_race`, `pure_sc2_leader_race`, `pure_sc2_member_race`, `map_vetoes` |
| `queue_leave` | Leave 1v1 queue | `DELETE /queue_1v1/leave` | `1v1` | — | *(empty)* |
| `queue_leave` | Leave 2v2 queue | `DELETE /queue_2v2/leave` | `2v2` | — | *(empty)* |
| `leaderboard` | View 1v1 leaderboard | `GET /leaderboard_1v1` | — | — | *(empty)* |
| `leaderboard` | View 2v2 leaderboard | `GET /leaderboard_2v2` | — | — | `game_mode` (`"2v2"`) |
| `profile` | View profile | `GET /player/{uid}/profile` | — | — | *(empty)* |
| `match_confirm` | Confirm 1v1 match | `PUT /matches_1v1/{id}/confirm` | `1v1` | yes | `game_mode`, `match_id` |
| `match_confirm` | Confirm 2v2 match | `PUT /matches_2v2/{id}/confirm` | `2v2` | yes | `game_mode`, `match_id` |
| `match_abort` | Abort 1v1 match | `PUT /matches_1v1/{id}/abort` | `1v1` | yes | `game_mode`, `match_id` |
| `match_abort` | Abort 2v2 match | `PUT /matches_2v2/{id}/abort` | `2v2` | yes | `game_mode`, `match_id` |
| `match_report` | Report 1v1 result | `PUT /matches_1v1/{id}/report` | `1v1` | yes | `game_mode`, `match_id`, `report` |
| `match_report` | Report 2v2 result | `PUT /matches_2v2/{id}/report` | `2v2` | yes | `game_mode`, `match_id`, `report` |
| `replay_upload` | Upload 1v1 replay | `POST /replays_1v1/{id}/upload` | `1v1` | yes | `game_mode`, `match_id`, `upload_status`, `auto_resolved`, `replay_id` |
| `replay_upload` | Upload 2v2 replay | `POST /replays_2v2/{id}/upload` | `2v2` | yes | `game_mode`, `match_id`, `upload_status`, `auto_resolved`, `replay_id` |

---

## `player_update`

State changes to a player record. `discord_uid` is the player being changed (not the admin, if an admin triggered it). Written inside transition methods, not endpoints.

| Action | Trigger | Source | `target_discord_uid` | `event_data` keys |
|---|---|---|---|---|
| `profile_update` | First-time setup | `_player.setup_player()` | — | `player_name`, `alt_player_names`, `battletag`, `nationality`, `location`, `language`, `completed_setup`, `completed_setup_at` |
| `nationality_update` | Country change | `_player.set_country_for_player()` | — | `field_changes.nationality.{before, after}` |
| `tos_update` | ToS accept/decline | `_player.set_tos_for_player()` | — | `field_changes.accepted_tos.{before, after}` |
| `ban_toggle` | Admin bans/unbans | `_admin.toggle_ban()` | — | `field_changes.is_banned.{before, after}` |
| `referral_submission` *(success)* | Referral code used | `_player.submit_referral()` | Referrer UID | `status` (`"success"`), `referral_code`, `referred_at` |

Note: `player_command` events for `setup`, `termsofservice`, and `setcountry` are *also* logged at the endpoint level — so these actions produce two event rows each: one `player_command` (the request) and one `player_update` (the state change).

---

## `admin_command`

Admin-initiated commands. `discord_uid` is the admin.

| Action | Trigger | Endpoint | `target_discord_uid` | `game_mode` | `match_id` | `event_data` keys |
|---|---|---|---|---|---|---|
| `ban` | Toggle ban | `PUT /admin/ban` | Banned player | — | — | `target_discord_uid`, `new_is_banned` |
| `statusreset` | Reset stuck status | `PUT /admin/statusreset` | Target player | — | — | `target_discord_uid`, `old_status` |
| `match_view` | View 1v1 match | `GET /admin/match/1v1/{id}` | — | — | yes | `match_id` |
| `match_view` | View 2v2 match | `GET /admin/match/2v2/{id}` | — | `2v2` | yes | `match_id` |
| `resolve` | Resolve 1v1 conflict | `PUT /admin/resolve` | — | `1v1` | yes | `game_mode`, `match_id`, `result` |
| `resolve` | Resolve 2v2 conflict | `PUT /admin/resolve/2v2` | — | `2v2` | yes | `game_mode`, `match_id`, `result` |
| `snapshot` | 1v1 system snapshot | `GET /admin/snapshot` | — | — | — | *(empty)* |
| `snapshot_2v2` | 2v2 system snapshot | `GET /admin/snapshot/2v2` | — | — | — | *(empty)* |

---

## `owner_command`

Owner-only commands. `discord_uid` is the owner.

| Action | Trigger | Endpoint | `target_discord_uid` | `event_data` keys |
|---|---|---|---|---|
| `admin_toggle` | Promote/demote admin | `PUT /owner/admin_toggle` | Target user | `target_discord_uid`, `action` (`"promoted"`/`"demoted"`), `new_role` |
| `set_mmr` | Directly set MMR | `PUT /owner/mmr` | Target player | `target_discord_uid`, `race`, `old_mmr`, `new_mmr` |

---

## `match_event`

Match lifecycle transitions. Written inside transition methods. `game_mode` and `match_id` are always set.

### 1v1

`discord_uid` is the acting player unless noted. Player keys use `p1_`/`p2_` prefix.

| Action | Trigger | `discord_uid` | `event_data` keys |
|---|---|---|---|
| `match_found` | Matchmaker pairs two players | `1` (backend) | `game_mode`, `match_id`, `p1_uid`, `p2_uid`, `p1_name`, `p2_name`, `p1_race`, `p2_race`, `p1_mmr`, `p2_mmr`, `map_name`, `server_name` |
| `match_confirmed` | Player confirms | Acting player | `game_mode`, `match_id`, `both_confirmed` |
| `match_aborted` | Player aborts | Acting player | `game_mode`, `match_id`, `aborter_uid`, `p1_uid`, `p2_uid` |
| `match_abandoned` | Confirmation timeout (60s) | `1` (backend) | `game_mode`, `match_id`, `p1_uid`, `p2_uid`, `p1_report`, `p2_report` |
| `match_completed` | Both players agree on result | `1` (backend) | `game_mode`, `match_id`, `result`, `p1_uid`, `p2_uid`, `p1_mmr_change`, `p2_mmr_change` |
| `match_completed` | Replay auto-resolve | `1` (backend) | Same as above + `via` (`"replay_auto_resolve"`), `uploader_discord_uid` |
| `match_conflict` | Players report conflicting results | `1` (backend) | `game_mode`, `match_id`, `p1_uid`, `p2_uid`, `p1_report`, `p2_report` |
| `match_resolved` | Admin resolves conflict | Admin UID | `game_mode`, `match_id`, `result`, `p1_uid`, `p2_uid`, `p1_mmr_change`, `p2_mmr_change` |

### 2v2

Same lifecycle, `game_mode` = `"2v2"`. Team keys use `t1_`/`t2_` and `team_N_player_N_` prefixes.

| Action | Trigger | `discord_uid` | `event_data` keys |
|---|---|---|---|
| `match_found` | Matchmaker pairs two teams | `1` (backend) | `game_mode`, `match_id`, `team_{1,2}_player_{1,2}_discord_uid`, `team_{1,2}_player_{1,2}_name`, `team_{1,2}_player_{1,2}_race`, `team_{1,2}_mmr`, `map_name`, `server_name` |
| `match_confirmed` | Player confirms | Acting player | `game_mode`, `match_id`, `all_confirmed` |
| `match_aborted` | Player aborts | Acting player | `game_mode`, `match_id`, `aborter_uid` |
| `match_abandoned` | Confirmation timeout (60s) | `1` (backend) | `game_mode`, `match_id`, `t1_report`, `t2_report` |
| `match_completed` | Both teams agree on result | `1` (backend) | `game_mode`, `match_id`, `result`, `t1_mmr_change`, `t2_mmr_change` |
| `match_completed` | Replay auto-resolve | `1` (backend) | Same as above + `via` (`"replay_auto_resolve"`), `uploader_discord_uid` |
| `match_conflict` | Teams report conflicting results | `1` (backend) | `game_mode`, `match_id`, `t1_report`, `t2_report` |
| `match_resolved` | Admin resolves conflict | Admin UID | `game_mode`, `match_id`, `result`, `t1_p1_uid`, `t1_p2_uid`, `t2_p1_uid`, `t2_p2_uid`, `t1_mmr_change`, `t2_mmr_change` |

---

## `system_event`

Backend-initiated system operations. `discord_uid` is always a sentinel.

| Action | Trigger | `discord_uid` | `game_mode` | `event_data` keys |
|---|---|---|---|---|
| `matchmaking_wave` | 1v1 matchmaker runs (every 60s) | `1` (backend) | — | `queue_size`, `matches_created`, `remaining_queue` |
| `matchmaking_wave` | 2v2 matchmaker runs (every 60s) | `1` (backend) | — | `game_mode` (`"2v2"`), `queue_size`, `matches_created`, `remaining_queue` |
| `guild_member_join` | New member joins Discord server | `2` (bot) | — | `discord_username`, `account_age_days`; `target_discord_uid` = joining member |
| `queue_notify_wave` | Queue activity DMs sent | `1` (backend) | `1v1`/`2v2`/`FFA` | `notified_discord_uids`, `notified_count`, `cooldowns` |

---

## Source file index

| File | Events written |
|---|---|
| `backend/api/endpoints.py` | `greeting`, `first_setup_started`, `first_setup_completed`, `setup`, `termsofservice`, `setcountry`, `queue_join`, `queue_leave`, `leaderboard`, `profile`, `match_confirm`, `match_abort`, `match_report`, `replay_upload`, `ban`, `statusreset`, `match_view`, `resolve`, `snapshot`, `snapshot_2v2`, `admin_toggle`, `set_mmr`, `guild_member_join` |
| `backend/orchestrator/transitions/__init__.py` | `setup_survey_submitted`, `referral_pitch_generated` |
| `backend/orchestrator/transitions/_player.py` | `referral_submission` (success + failure), `nationality_update`, `profile_update`, `tos_update` |
| `backend/orchestrator/transitions/_admin.py` | `ban_toggle`, `match_resolved` (1v1 + 2v2) |
| `backend/orchestrator/transitions/_match.py` | `matchmaking_wave` (1v1), `match_found`, `match_confirmed`, `match_aborted`, `match_abandoned`, `match_completed`, `match_conflict` |
| `backend/orchestrator/transitions/_match_2v2.py` | `matchmaking_wave` (2v2), `match_found`, `match_confirmed`, `match_aborted`, `match_abandoned`, `match_completed`, `match_conflict` |
| `backend/orchestrator/transitions/_replay.py` | `match_completed` via replay auto-resolve (1v1 + 2v2) |
| `backend/orchestrator/transitions/_notifications.py` | `queue_notify_wave` |

## Dual-logging pattern

Several user actions produce **two** event rows:

1. A `player_command` row from the endpoint (records the request and its parameters)
2. A `player_update` row from the transition (records the state change with before/after values)

This applies to: **setup** (`setup` + `profile_update`), **termsofservice** (`termsofservice` + `tos_update`), **setcountry** (`setcountry` + `nationality_update`).

The same pattern occurs for admin actions: the endpoint logs an `admin_command` row while the transition logs a `player_update` (`ban_toggle`) or `match_event` (`match_resolved`).
