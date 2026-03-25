What remains?

❌⏰✅

# FINISH BY PRE-BETA

- ✅ Write pre-beta feature announcement
- ⏰ Write pre-beta launch announcement
- ⏰ Re-write Terms of Service
- ⏰ Apparently /setup is still not intuitive
    - ⏰ Add some descriptions explaining what User ID, BattleTag, alternative IDs, nationality, location are
- ✅ Add instructions under MatchInfoEmbed (in a new embed):
    - ✅ How to change servers
    - ✅ How to join a channel
    - ✅ How to find opponents
    - ✅ How to host a lobby or join a lobby your opponent hosted
    - ✅ Lobby guide can be toggled
        - ✅ New players table column
- ⏰ Update untranslated keys
    - ⏰ Send to localizers:
        - ⏰ koKR: Vanya
        - ⏰ esMX: Kat
        - ⏰ zhCN: Sprite, DragonVector
        - ⏰ ruRU: Rake, ZaRDieNT, ShadowDragon
- ✅ `/snapshot 2v2` needs to include flags and races
    - ✅ Come up with letter-grid-style display
    - ✅ Fixed the display to look much more like `/snapshot 1v1` across all embeds
- ⏰ `/profile` stats could be better
    - ⏰ Improve overall look and feel
    - ⏰ Add 2v2 stats...but how? Just sum across all partners?
    - Probably just figure this out later
- ✅ Set global cooldown on bot stuff?
    - ❌ Do I even need to set this?
        - Most views use a default of 180s
        - ActivityChartView uses 600s
        - QueueSetupViews uses 300s
        - MatchFoundViews use 60s (1 minute to confirm)
        - MatchReportViews are unlimited so people can take as long as they need to report
        - ✅ These durations seem fine
- ✅ `/leaderboard 2v2` does not display flags
    - ✅ Flag filtering is broken
    - ✅ Embed does not show selected countries for filter
    - ✅ Come up with wide display 
    - ✅ Select parameters for entries on `/leaderboard 2v2` pages (probably 5 x 4 = 20 wide entries per page)
    - ✅ Examine LeaderboardEntry2v2 to see if we need more data
    - ❌ Optionally, display most recently played race combination as the races displayed on leaderboard
- ✅ Store canonical copies of migrated old database so I can easily launch the pre-beta
- ✅ Zip up the replays too?
    - ✅ Alpha replays zipped up
- ✅ Combine /termsofservice and /setup:
    - ✅ /termsofservice embed should become the first step in /setup
    - ✅ locale selection now comes earlier in the /setup
    - ✅ Players can now setup notifications in /setup
- ✅ Automatically send the /termsofservice embed/first step of /setup whenever someone messages the bot and they are a new user
- ✅ Create a channel manager microservice
    - Two endpoints:
        - Accept match information about two players, create a channel, send the match info embed inside it
            - This should return the message share link of the embed message to the backend
            - The backend should transmit the link to the bot
            - The bot should share the channel link to both players in the match notification so they know where to look
        - Delete a channel by message ID or channel ID
            - Happens when a match is resolved
            - Optional: time delay the deletion so we have time to clean a mess up if needed
            - Needs safety measures so the bot only can delete channels it created / specifically in its data tables
    - Players can optionally use this channel to coordinate once matched but they cannot find each other
    - ✅ It works now
    - ✅ Clean up the UI/presentation
- ✅ Rectify inconsistencies between 1v1 and 2v2
- ✅ Make sure 2v2-related functionality uses the keys
- ✅ Finish 2v2 implementation
- ✅ Quality check 2v2 implementation
    - Especially replay uploads
- ✅ Player names should be unique
- ✅ Player names cannot contain symbols
    - Letters only...
    - How do I tackle this for many languages and scripts?
- ❌ Make sure visibility is solid
    - ❌ Maybe some more admin/owner commands
        - ❌ Directly reading DataFrame rows
    - ❌ No longer a priority at this time
- ✅ Add some kind of health check and automatic resurrection for:
    - ✅ replay parsing process pool
    - ❌ DataFrames
        - write-through guarantees writes hit the DB
        - but not that DFs might not silently corrupt...(?)
        - ❌ skipped
- ✅ Add unit tests
    - They briefly test invariants, not numerical outcomes
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
    - ⏰ FFA TBD...

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

---

# `/snapshot 2v2` (design note)

The 1v1 snapshot sends three embeds: system stats (DataFrame sizes), queue entries, and active matches. The 2v2 snapshot should follow the same structure but insert a **parties** embed between system stats and queue, giving four embeds total: system stats → active parties → queue → active matches.

The parties embed shows every entry in `parties_2v2` (the in-memory dict keyed by leader UID). Each row should display the leader and member names, their status (`in_party` vs `queueing`), and how long the party has existed. This is the only state in the system with zero external visibility — it's never persisted to Supabase and has no other endpoint. Without it, debugging "we're in a party but can't queue" is impossible.

The queue embed mirrors the 1v1 version but displays party pairs instead of individual players. Each entry shows the leader and member side by side, their composition slots (BW/SC2/mixed), team MMR, and wait time. The active matches embed is analogous to 1v1 but shows all four players per match (two per team), the resolved composition (which team is BW, which is SC2), map, server, and elapsed time.

The main open question is display layout. 1v1 queue entries and match rows fit in monospace backtick strings because each row has two players. 2v2 doubles the player count per row, which will overflow Discord's embed width in monospace. Options: (a) stack team rows vertically (two lines per match instead of one), (b) abbreviate more aggressively (drop nationality, shorten names), or (c) use embed fields instead of monospace blocks. This needs to be prototyped with real data to see what actually fits before committing to a format.

---

# Discord Announcement

Hello @everyone,

The pre-beta phase of the SC: Evo Complete ladder arrives soon.

I want to take this time to share with you what you can look forward to:

## New Gamemodes

2v2 is coming to the ladder.
- The pre-beta will introduce functionality to create a party. **You must be in a party to play 2v2.** The 2v2 queue will not accept solo players.
- Your 2v2 MMR will be unique to each partner you play with — but not to each race, so you and your partner can freely queue with any races you like.
- The 2v2 ladder will feature both **BW + BW vs SC2 + SC2** and **BW + SC2 vs BW + SC2** matching.
    - You will be able to set a preferred **BW + BW**, **BW + SC2**, and **SC2 + SC2** team composition.

In addition, there may be seasonal gamemodes in the future, such as Archon or FFA variants.

## Improved Activity Visibility

One pattern that arose from the bot data during the alpha phase was the frequency with which players would just barely miss each other in down time.

To address this, we are introducing two new features:
- Opt-in notifications every time someone joins the ladder (tuneable to be no more than once per time period of your chosen duration).
- Public view access to the queue activity log, so you can see what times of the day and week have historically been most active.

## Improved Match Flow

During the alpha, a common pain point was uploading your replay and reporting the result of the match...only for your opponent to go AFK, leaving you stuck and unable to queue. Or worse, many players accidentally misreported match results while auto-piloting through the post-match process, requiring significant admin intervention.

Now, whenever possible, as soon as any player in your match uploads a replay, the system will automatically resolve the match and update your MMR based on replay data. This will eliminate the need for manual reporting in 99% of cases.

## New Locales

To support our core player communities from around the world, our localization crew is proud to present four new locales:

- 🇲🇽 esMX (Mexican Spanish)
- 🇰🇷 koKR (Korean)
- 🇷🇺 ruRU (Russian)
- 🇨🇳 zhCN (Simplified Chinese)

## Pricing and Monetization

In previous announcements, I openly discussed plans for monetizing the ladder. This has understandably worried many of our fans.

So, please allow me to assure you, the SC: Evo Complete ladder **will always be free to use** for core features — matchmaking, leaderboards, alternative gamemodes, and such. I will offer these at **no cost forever**, because the SC: Evo Complete community deserves proper practice infrastructure that is seamless and free of cheaters.

That said, there will be paid functionality in the future. Running a service of this nature is not free. I currently pay for all costs associated with hosting and development out of my own pocket. I do this because I love SC: Evo Complete, and I intend to keep doing so for as long as I can. However, if running the ladder costs me more than I can personally absorb, the ladder will go down.

Paid tiers and features will be introduced in the beta. I will do my best to ensure that these features make the ladder experience extra special for those who can give a bit back to what makes this mod great, without diminishing the experience for the masses.

## Before I go,

There will be more to look forward to in the pre-beta and beyond, not just ladder features but also the wider SC: Evo Complete multiplayer ecosystem. In particular, let's just say that it might be a good idea to start climbing the 1v1 leaderboard as soon as the pre-beta launches...

I look forward to releasing the pre-beta. See you soon!