What remains?

❌⏰✅

# FINISH BY PRE-BETA

- ⏰ Write pre-beta feature announcement
- ⏰ Re-write Terms of Service
- ⏰ Store canonical copies of migrated old database so I can easily launch the pre-beta
- ✅ Player names should be unique
- ✅ Player names cannot contain symbols
    - Letters only...
    - How do I tackle this for many languages and scripts?
- ⏰ Apparently /setup is still not intuitive
- ⏰ Make sure visibility is solid
    - Maybe some more admin/owner commands
        - Directly reading DataFrame rows
- ⏰ Add some kind of health check and automatic resurrection for:
    - replay parsing process pool
    - DataFrames
        - write-through guarantees writes hit the DB
        - but not that DFs might not silently corrupt...(?)
- ⏰ Add unit tests
- ✅ /notifyme needs to send an embed, not just a message, it's fugly right now
- ✅ Need some dashboard to help people see when peak hours are
    - ✅ Need to keep track of queue join attempts
    - ✅ the events table {event_type = player_command, action=queue_join, game_mode=1v1, performed_at=timestamp}
        - this gives us everything we need, just need to graph this
- ✅ /leaderboard is completely unimplemented
    - 1/7/21/21/21/21/8% splits
    - Ordinal rank calculation
    - Store in Leaderboard1v1 in StateManager
    - ✅ Need to spot check /leaderboard and the implementation code
- ✅ Every single time a match is resolved, we must trigger the leaderboard recalculation and wait for the result and then get it
    - ✅ The letter rank updates need to propagate to the match finalized embeds
    - ✅ And make sure the frontend gets the update too via WebSocket
- ✅ /profile looks weird
- ✅ /profile doesn't contain full T/W/L/D (win-rate %) statistics by race and aggregated
- ✅ Generally the UI is messed up everywhere
    - Especially /snapshot
    - ✅ Holy shit fix this
- ✅ /snapshot does not correctly show letter 
    - Currently shows `Z1 HyperONEFOUR`
    - It needs to show `D T2 US HyperONEFOUR`
- ✅ /snapshot displays matches that should have already been resolved
- ❌ Implement the infrastructure
    - ❌ of what??? I forgot. I had a thought here and dropped it. probably not important
- ✅ mmrs_1v1 W/L/D/T game counts desync from matches_1v1 when a match gets resolved more than once
    - Admin resolutions need to force a recalculation of the affected mmrs_1v1 rows
- ✅ Fix any other import issues (circular/lazy/etc.)
- ✅ Potentially split embeds/views/other components out of the command modules
    - queue_command.py is getting very large
- ✅ Maybe split up transitions.py
    - This is also getting pretty large

- ✅ Make HTML error codes explicit (4XX/5XX) instead of returning 200 everywhere
- ✅ Fix mypy error suppressions and underlying issues
- ✅ Migrate some config variables into ENV, there are many that would be convenient to have moved to backend/core/config.py or bot/core/config.py or even loaded from ENV directly
    - Especially the current season
    - Actually we should just centralize all of them, no private constants, just move them all to config
- ✅ Fix circular imports/coupling with WebSocket by isolating whatever is causing conflicts into a differnet module
- ✅ Fix duplicated `_format_verification`
- ✅ Fix `admin_resolve_match` branch duplication
    - There is shared logic between the MMR adjusting paths and the abort/abandoned paths that could be consolidated
- ✅ Fix `on_ready()` firing on the bot on every reconnect
    - More specifically we should have some kind of module level flag that prevents initializing a new aiohttp session, a new MessageQueue, re-registering all commands, etc..
- ✅ Resolve potentially duplicated config values between bot and backend
- ✅ Find and fix all asserts, change them to errors

# FINISH DURING PRE-BETA

- ✅ Need some way for players to see who is online
    - ✅ Activity notifier when someone queues
    - ✅ Analytics charts showing when are peak hours
- ✅ Fill out localization strings
    - ⏰ Localizers will do this slowly
- ⏰ Add 2v2 and FFA gamemodes
    - ✅ Added 2v2

# FINISH BY FULL BETA

- Acquire funding for SEL Ladder Invitational (up to $4,000 for A-Tier)
- Make a 1-2 minute hype trailer
- Add Stripe integration
    - Two tiers:
        - Basic Tier (free)
            - Unlimited games and core features
            - Access to /profile and /leaderboard
        - Supporter Tier (paid, $5-10/month / $50-100/year or PWYW?)
            - Additional analytics or cosmetics features
            - Full MMR timeline charts
            - Winrate analysis by race, time, map, etc.
            - Perks might not be ready for full beta launch

---

# Queue activity & notify (design backlog — circle back)

This section captures decisions for **`/activity`** and **`/notifyme`** so implementation can proceed without re-deriving product intent.

## Events and “who left the queue”

- **Persist** `queue_join` (and when ready, `queue_leave`) on the existing **`events`** table with consistent `game_mode`, `discord_uid`, `performed_at`, and small `event_data` as needed.
- **For `/activity` v1**, treat analytics as **queue join attempts only** — no requirement (yet) to pair joins with exits. That keeps the first chart simple and avoids incomplete interval logic.
- **Ways a player effectively leaves the queue** (for *future* dwell-time / pairing work, not required for the join-attempt chart):
    1. **`queue_leave`** (explicit).
    2. **Match lifecycle** — include their `discord_uid` in a **`match_found`** (or equivalent) event so intervals can close when they are matched.
    3. **Admin `statusreset`** — record something like **`event_type = admin_command`**, **`action = statusreset`**, **`target_discord_uid = {discord_uid}`** (acting admin in `discord_uid` or documented in `event_data`). When pairing join→end, treat this like a synthetic leave for that target uid.
- Until join/leave/match/statusreset are all emitted reliably, **time-in-queue** derived from pairing will be noisy; **join-attempt counts** remain the robust default metric.

## `/activity` (DM-only)

- **Chart type:** **Line plot** (users expect a trend over time), not a bar histogram — though both are aggregations over buckets.
- **Bucket width:** **`ACTIVITY_QUEUE_JOIN_CHART_BUCKET_MINUTES`** in **[`common/config.py`](../common/config.py)** (default **5**). Re-export via `backend/core/config.py` and `bot/core/config.py`. Backend aggregation API buckets `queue_join` rows into intervals of that width; bot builds **matplotlib → PNG** and attaches to the DM.
- **Range control:** `discord.ui.Select` (and optional slash args) to change the displayed window; aligns with earlier “initial/final range” UX.
- **`game_mode`:** **1v1** first; **2v2 / FFA** stubbed in UI until modes exist.
- **Spam / deduplication:**
    - Implement **deduped** join series in the backend using **`ACTIVITY_QUEUE_JOIN_DEDUPE_SECONDS`** (same `common/config.py`): e.g. do not increment the deduped count for a `queue_join` if the previous countable event for that `(discord_uid, game_mode)` was another `queue_join` inside the window, until a `queue_leave`, match event, or **`statusreset`**-style row “resets” the gate.
    - **Product v1:** expose **raw** join counts in the chart only; keep **deduped** logic implemented and tested so a second series or toggle can be wired later without refactor.
- **Security:** low adversarial expectation; optional max date range / max points on the API is still a cheap guard.

## `/notifyme` (DM-only)

- **Preferences** live on **`notifications`** (extend table): per-mode opt-in flags (stub 2v2/FFA), plus per-user cooldown (minutes); keep **`read_quick_start_guide`** as today.
- **Default cooldown** when not specified on the command: **`QUEUE_NOTIFY_COOLDOWN_MINUTES_DEFAULT`** in **`common/config.py`**, re-exported the same way.
- **Cooldown enforcement:** in-memory `last_sent` map (lost on restart is acceptable).
- **DM delivery:** **low-priority** [message queue](../bot/core/message_queue.py) jobs.
- **Content:** anonymous embed (“Someone is queueing now!” / mode-aware), **no joiner identity**; footer states when the next ping is allowed per their settings.
- **Gates:** DM channel, **setup + ToS + not banned**, **opt-in** only.

## Config summary

| Constant | Location | Purpose |
|----------|----------|---------|
| `ACTIVITY_QUEUE_JOIN_CHART_BUCKET_MINUTES` | `common/config.py` | Line chart x-axis bin width (minutes) |
| `ACTIVITY_QUEUE_JOIN_DEDUPE_SECONDS` | `common/config.py` | Deduped series gap rule (implementation-first; UI later) |
| `QUEUE_NOTIFY_COOLDOWN_MINUTES_DEFAULT` | `common/config.py` | Default `/notifyme` cooldown / DB row default |

## Deferred

- **Weekly digest** of activity — owner will decide separately.
- **Dwell time** reports from join→(leave | match | statusreset) pairing — after event coverage is complete.