## PRE-ALPHA

### Account Configuration
- ✅ Update Terms of Service for closed alpha/open beta stage
  - ✅ Create a Rentry/Github document for this and just link it
  - ✅ Create a page on official SC: Evo website
- ✅ Fix country setup descriptions for XX (nonrepresenting) / ZZ (other)
- ✅ /setup persists pre-existing values as defaults (so you don't have to fill them all out again to change one thing)
- ✅ nulling of alt names is properly recorded in action logs table

### Admin & Monitoring
- ✅ Add automatic logging/pinging of admins when a match disagreement arises
  - ✅ Send replay data to admins
- ✅ Add an interface to allow admins to view conflicts in matches and resolve with 1 click

### Core Architecture & Performance
- ✅ Complete DataAccessService migration from legacy db_reader/db_writer pattern
- ✅ In-memory hot tables using Polars DataFrames for sub-millisecond reads
- ✅ Asynchronous write-back queue for non-blocking database operations
- ✅ Singleton pattern ensuring consistent data access across application
- ✅ Service dependency injection with app_context.py
- ✅ Performance monitoring with comprehensive timing and memory tracking
- ✅ Memory leak fix: MatchFoundView lifecycle management
  - ✅ Added synchronous `_cleanup_view()` method for deterministic cleanup
  - ✅ Proper removal from tracking dictionaries (MatchFoundViewManager, channel_to_match_view_map)
  - ✅ Break circular references with `clear_items()` to enable garbage collection
  - ✅ Added telemetry tracking for leaked instances (RSS, view counts, GC metrics)
  - ✅ Expected: Reduce 12h memory growth from 1GB to <150MB (90-95% improvement)
- ✅ 99%+ performance improvement across all critical operations
  - ✅ Rank lookup: 280-316ms → 0.00ms (99.9% improvement)
  - ✅ Player info lookups: 500-800ms → <2ms (99.7% improvement)
  - ✅ Abort count lookups: 400-600ms → <2ms (99.5% improvement)
  - ✅ Match data lookups: 200-300ms → <2ms (99% improvement)
  - ✅ Embed generation: 400-500ms → <50ms (90% improvement)

### Critical Bug Fixes
- ✅ Leaderboard ranks: Fixed missing rank calculations and display
- ✅ Match result calculation: Corrected player report interpretation (0=draw, 1=P1 wins, 2=P2 wins)
- ✅ Abort flow: Fixed "Aborted by Unknown", queue lock releases, and race conditions
- ✅ Replay database writes: Fixed missing uploaded_at field and replay update handlers
- ✅ MMR updates: Fixed in-memory MMR updates and frontend display
- ✅ Player names: Fixed leaderboard displaying "PlayerUnknown" → actual player names
- ✅ Shared replay views: Fixed players seeing each other's replay status
- ✅ Graceful shutdown: Fixed event loop conflicts and task cancellation
- ✅ Error handling: Removed all fallback values, promoting explicit error handling
- ✅ Database consistency: Fixed schema mismatches and missing field handlers

### Database & Infrastructure
- ✅ Define PostgreSQL schema
- ✅ Full migrate to PostgreSQL
  - ✅ Hybrid architecture with SQLAlchemy adapter allows local testing with SQLite and remote host testing with PostgresSQL
- ✅ Store replays in separate persistent storage and not in SQL tables
- ✅ Optimize the shit out of PostgreSQL queries
  - ✅ Bundle queries
  - ✅ Change query types
- ✅ Implement spawning helper processes for replay parsing (multiprocessing with ProcessPoolExecutor)
  - ✅ Created parse_replay_data_blocking() worker function
  - ✅ Implemented global process pool with configurable workers
  - ✅ Updated on_message() to use run_in_executor()
  - ✅ Comprehensive test suite (6/6 tests passing)
  - ✅ Full documentation and demonstration scripts
- ✅ Implement service locator pattern for global service instances
- ✅ Migrate timestamps from TIMESTAMP to TIMESTAMPZ with explicit UTC declaration
  - ✅ Source-internal architecture continues to assume UTC

### Legacy Cleanup
- ✅ De-activate the outdated /activation command

### Matchmaking & Match Flow
- ✅ Fill out the full cross-table for 16 regions
- ✅ Get the matchmaker to correctly assign server based on the cross-table
- ✅ Add more information/clean up existing information on the match found embed
- ✅ Matchmaker now assigns matches in waves occurring every 45 seconds, up from 5, trading time for fairer matches
- ✅ Expanding MMR window for matchmaking scales dynamically with active player count and proportion of active player count 
- ✅ 99 race conditions on the wall, 99 race conditions, take one down, pass it around, 157 race conditions on the wall...
- ✅ Forbid queueing while a match is active, or queueing again while already queueing.
- ✅ Consolidated management of QueueSearchingView locks into a single class

### Match Reporting & Completion
- ✅ Make the match reporting pipeline more robust
- ✅ Fix race conditions resulting in the first player to report match result not getting any updates
- ✅ Add replay uploading and storage to the database (no automatic parsing for now)
- ✅ Fix some lag associated with both players receiving confirmation of match results
- ✅ Fix the main embed being overwritten with an error embed when players report disagreeing match results
- ✅ Add an option to abort 3 matches a month. Aborting matches causes no MMR change.
  - ✅ Exceeding this count and throwing games/smurfing will result in bans.
- ✅ Fix the display of remaining abortions to players
- ✅ Match completion on backend is properly abstracted away from frontend
- ✅ Consolidated management of MatchFoundView locks into a single class

### MMR & Ranking System
- ✅ MMR is now ELO-like rather than classic ELO spec-compliant (divisor = 500 rather than 400; 100-point gap predicts a 62-38 win chance instead of 64-36)
- ✅ MMR is now integer-based rather than float-based
- ✅ MMR curve now more closely resembles that of Brood War
- ✅ Add dynamic rank calculations (S/A/B/C/D/E/F) to leaderboard and player profiles
- ✅ Add rank filter toggling
- ✅ Edit and add rank emotes

### Replay System
- ✅ Replays are now redirected to storage instead of being stored directly in tables
- ✅ Tables now store replay paths
- ✅ Move replays to a dedicated table and add pointer logic between tables
- ✅ Parse replays for basic info: players, player races, observers, map, timestamp, length, etc.
- ✅ Send a message to the user with this information when they upload a replay
- ❌ Update the MatchFoundViewEmbed with this information
  - ✅ Send a new embed message with this information
- ✅ Check that uploaded replays comply with the match parameters
  - ✅ Throw a warning if the map link do not match exactly
  - ❌ Reject the replay outright if the wrong races are present

### System Hardening & Optimization
- ✅ No 60-second leaderboard refresh loop, invalidate cache specifically only when services modify MMR
- ✅ Remove synchronous leaderboard path (async path should not fall back to it)
- ❌ Implement a smarter prune protection algorithm than using string matching
  - ✅ Still using string matching but it's less stupid now
- ❓ Implement frontend mock testing
  - ✅ Characterization/regression tests including simulation of frontend flows but not true UI mocking

### User Interface & Commands
- ✅ Command guard: Fully decoupled command guarding errors from frontend
- ✅ Add a /profile page to view one's own MMRs and settings
- ✅ Add flag emojis to country dropdowns in /setup (including XX and ZZ custom emotes)
- ✅ Add flag emojis to /setcountry confirmation embeds
- ❌ Implement action deferral? And add loading bars + disable UI while waiting
  - ✅ Removed all action deferral, since the bot is now so fast that deferral hurts UX

### MORE RANDOM BUGS???
- ✅ Accepting ToS does not properly record having accepted (FIXED)

### Admin Commands
- Adjust MMR: ✅ Seems functional
  - ✅ MMR successfully updated
  - ✅ Player does not get a notification ([AdminCommand] Cannot send notification: bot instance not available)
- Clear Queue: ✅ Incomplete
  - ✅ Players are removed from the queue
  - ✅ Player does not get a notification ([AdminCommand] Cannot send notification: bot instance not available)
  - ✅ Player remains in queue-locked state, cannot queue again
- Player: ✅ Mostly functional
  - ✅ All information technically present and accounted for
  - ✅ Active Matches list needs to be pruned down
  - ✅ To be honest, this should just follow the formatting for the user /profile command, but with extra sections
- Snapshot: ✅ Functional
  - ✅ Info technically all present
  - ✅ Could/should include more detail about
    - Players in queue and their races
    - Ongoing matches and their IDs and players
    - A couple other metrics
- Match: ✅ Functional, but could use improvement
  - ✅ JSON payload is complete
  - ✅ Could use a guide for admins on how to interpret values
- Reset Aborts:
  - ✅ Abort count successfully updated
  - ✅ Player does not get a notification ([AdminCommand] Cannot send notification: bot instance not available)
  - ✅ Confirm embed does not show the old amount, only the complete embed does
- Resolve Match: ✅ Broken
  - ✅ Never recognizes a conflicted state
  - ✅ Should be able to resolve the match no matter what
- Remove Queue: ✅ Incomplete
  - ✅ Players are removed from the queue
  - ✅ Player does not get a notification ([AdminCommand] Cannot send notification: bot instance not available)
  - ✅ Player remains in queue-locked state, cannot queue again
- Needed additional features:
  - ✅ Match resolution must remove queue-locked state mid-match

### Other Last Minute Stuff
- ✅ Improve the matchmaking algorithm
  - ✅ Locally optimal solution instead of greedy matching
  - ⏰ Fill out pings in server cross-table
  - ⏰ Adjust matchmaking bias a little based on ping quality and fairness
- ✅ Send a follow-up message to players who do not confirm match in a third of the abort countdown timer after match assignment
- ✅ Send a dismissable message to players who enter a match involving BW Protoss about how to avoid Shield Battery lag
- ✅ I already updated admins.json with "owner" and "admin" roles, add an owner-only command to adjust admins while the bot is up

### MORE LAST MINUTE STUFF
- ✅ Figure out what cache handles fingerprint official SC: Evo Complete Extension mod
- ✅ Add cache handles column and cache handles check boolean to replays table
- ✅ Add functionality to replay parser to validate cache handles
- ✅ Add cache handle data to mods.json
- ✅ Add all needed emotes for the bot into test server
- ✅ Overwrite emotes in emotes.json
- ❌ Make admin commands DM-only???
- ✅ Actually, do send all match results to a dedicated channel
- ✅ Add the bot to the official server
- ✅ Test and tidy up every command (DO LAST)
  - ❌ /help
    - ✅ Unregistered for now
  - ✅ /leaderboard
  - ✅ /profile
  - ✅ /queue
  - ✅ /setcountry
  - ✅ /setup
  - ✅ /termsofservice
  - ✅ /admin adjust_mmr
  - ✅ /admin ban
  - ✅ /admin snapshot
  - ✅ /admin clear_queue
  - ✅ /admin match
  - ✅ /admin player
  - ✅ /admin resolve
  - ✅ /admin remove_queue
  - ✅ /admin reset_aborts
  - ✅ /admin unblock_queue
  - ✅ /owner admin
- ✅ Clean up the /help command
- ✅ Check every command to add a "❌ Clear/Cancel" button to it


### November 8, 2025

- ✅ Fix Holy World Korean typo
- ✅ Fix map links linking to the wrong maps
- ✅ Fix mod links linking to the wrong mods
- ✅ Clear all BattleTags
- ✅ Make BattleTag regex loose
- ✅ Make alt nickname regex loose
- ✅ Add a short tutorial for new players queueing up
- ❓ Add an image explaining that you need to upload a replay
- ❓ Add an image explaining how to report once you upload a replay
- ✅ Display BattleTag and Discord UID (via mention) in MatchFoundViewEmbed so players can reach out to each other
- ❓ Fix `/admin match` not showing replay embeds
- ✅ Fix `/admin snapshot` not showing enough players queueing and matches (gets truncated at too low of a number)
- ❌ Fix `/admin snapshot` so it triple-backtick (code block) escapes players queueing and matches in-progress, and do it separately
  - ✅ Didn't do this, so I could mention users directly
- ✅ Fix `/admin snapshot` showing {p1_name} vs {p2_name} (None) (is this supposed to be a map???)
- ✅ Fix `/admin` commands not being able to use `player_name` instead of `@mention`, `discord_username`, or `discord_uid`
  - ✅ Implement a helper method that all `/admin` commands needing a player input can use
- ❌ Use `matches_1v1` table for W-L-D records instead of the less reliable `mmrs_1v1`
  - ❌ `/profile` and `/admin player` total W-L-D looks wrong
  - ✅ `mmrs_1v1` table game counts periodically synchronize using `matches_1v1` table as truth
- ✅ Add something to let people know their opponent confirmed a match
- ✅ Shorten the Confirm Match/Abort Match timer
- ⏰ ADD REMINDERS TO CONFIRM AND UPLOAD REPLAYS
- ✅ Fix leaderboard `player_name` field
- ✅ Fix a million memory leaks(?)
- ✅ Write up announcement explaining fixes
- ✅ Write up announcement asking for Korean/Simplified Chinese/Spanish admins

### Announcement

**General Changes Made**

**Bugs Fixed**
- Fixed an issue where games played on `[SC:Evo] Holy World (홀리월드)` would not be recognized by the bot due to the Korean name being misspelled as `홀리울드`
- Fixed an issue where the links for the map `[SC:Evo] Radeon (라데온)` were incorrect
- Fixed an issue where the links for the mod `SC: Evo Complete` were incorrect
- Fixed an issue where BattleTags could not be registered in non-Latin (non-English) characters
- Fixed an issue where `/leaderboard` did 
- Fixed an issue where `/profile` did not display total games/wins/losses/draws accurately


### November 9, 2025
- ✅ Singapore is displayed as being part of Asia server instead of Americas server
  - ✅ Switched region code from "AS" to "AM"
- ⏰ Matchmaker cycles are not sychronized with the itmers displayed to players in /queue
- ✅ Discord IDs are not being cached by the bot since bot lacks member intents
  - ✅ Added `intents.members = True`
- ⏰ Main ID allows non-English characters
  - ✅ Validator now only allows 3-12 English characters
  - ⏰ Update `/setup` UI accordingly
- ❌ Reset `/setup` for players with non-English player names
  - ✅ Manually swapped their names
- ✅ Prettify with the race emotes everywheree!
  - ✅ Added race emotes to race select in `/queue`
  - ✅ Added game emotes to map vetoes in `/queue`
- ✅ Services are instantiated several times, including `/queue` matchmaker
- ✅ Two separate `/queue` instances exist quietly
  - ✅ Merged the queues
- ✅ `/admin match` doesn't show replay details for matches completed in the current bot deployment sesion
  - ✅ Fixed match resolution to add replay details to memory in addition to queuing a DB write
- ✅ New users may find the bot unresponsive on their first command use
  - ✅ Creating new user profile should no longer be a blocking action 
- ⏰ 
- ⏰ 
- ⏰ Test and tidy up every command (DO LAST)
  - ✅ /leaderboard
  - ✅ /profile
  - ✅ /queue
  - ✅ /setcountry
  - ✅ /setup
  - ✅ /termsofservice
  - ✅ /admin adjust_mmr
  - ✅ /admin ban
  - ✅ /admin snapshot
  - ✅ /admin clear_queue
  - ✅ /admin match
  - ✅ /admin player
  - ✅ /admin resolve
  - ✅ /admin remove_queue
  - ✅ /admin reset_aborts
  - ✅ /admin unblock_queue
  - ✅ /owner admin

### November 11, 2025
- ✅ Fixed `/admin snapshot` embed blanks being the wrong width
- ✅ Fixed an issue where MMR difference optimization in the matchmaking algorithm could cause a player queuing with both BW and SC2 to be matched against themselves
- ✅ Fixed an issue with buttons and dropdowns being displayed after no longer needed, causing client end lag and server memory leaks
- ✅ Fixed an issue with `/leaderboard` generating an entirely new embed instead of editing the existong one


### November 12, 2025
- ✅ Uploading listener for replays on `/queue` MatchFoundView can quietly fail
- ✅ Some commands have unnecessary terminal embed buttons, like `/profile` and `/termsofservice`, causing unnecessary lag

### November 12-15, 2025
- ✅ Race condition when mutating `_players_df` exists that causes MatchFoundView to not properly load components
- ✅ `/admin snapshot ` only shows rank for ONE of the races being queued with, not both
- ⏰ Maybe automatically set `view=None` on `/leaderboard` when `GLOBAL_TIMEOUT` elapses?
- ⏰ Add a third alternate ID
- ⏰ Rework `/setup` flow so users can read an embed before setting up the modal
  - ⏰ Explain that main ID, BattleTag, and alternate IDs will be used for name matching in replays
- ⏰ Implement automating match reporting based on replay parsing verification results
- ⏰ Players who have been waiting a long time don't get priority if they are on follow side of matchmaking
- ⏰ Explanation of opponent match confirm and opponent match reported notifications is confusing
- ⏰ Explanation of replay validation results is confusing
- ✅ Update the maps from TLMC21 versions to ladder versions
- ✅ Swap out Death Valley for Ruby Rock
- ⏰ Fix cross-tables for China

### ANNOUNCEMENT: November 13, 2025

## General Changes
- Map pool updated:
  - `[TLMC21] Celestial Enclave` replaced with `Celestial Enclave LE`
  - `[SC:Evo] Death Valley (데스밸리)` replaced with `Ruby Rock LE`
  - `[TLMC21] Mothership` replaced with `Mothership LE`
- `/queue` "Searching..." embed is now replaced with a short message when a match is found
- Clarified wording on the Match Confirmation embed: both messages now explain that **both you and your opponent** must confirm the match before it is safe to play
- Added match reporting instructions to "Match #{number} - 📝 Your Opponent Reported" embed
- `/leaderboard` buttons and dropdowns are removed after 15 minutes (global timeout cooldown)
  - This should reduce client lag on lower-end devices
- Adjusted server assignemnt tables for China and Taiwan/Hong Kong/Macau regions
## Bug Fixes
- Fixed an issue where players have been waiting for a long time did not get priority matchmaking
- Fixed an issue with player data sychronization at match creation, causing some players to not receive notifications that a match was found
## Other Notices
- It is normal for buttons from old messages (>15 minutes, or >2.5 hours for `/queue`-related messages) to become unresponsive
  - This is NOT a bug
- `/setup` requires you to press the `✅ Confirm` button in order for your changes to be accepted.
  - This is NOT a bug
- Please include full screenshots of your DMs/interactions with the bot when reporting bugs
  - We cannot thoroughly investigate issues without these screenshots and ladder staff have been instructed to de-prioritize reports that do not include documentation


## PRE-BETA

- Command timeouts:
  - ⏰ Check that everything lasts as long as it needs to
- Gamemodes:
  - ⏰ Add support for no-party 2v2s
  - ⏰ Add support for forming parties
  - ⏰ Add support for party-okay 2v2s
- Localization:
  - ⏰ Add support for koKR and other languages
  - ⏰ Replace 1 million hardcoded formatted strings...sobbing
- Matchmaking:
  - ⏰ Add relative ping weights for each matchup in the cross-table
  - ⏰ More ping-aware algorithm to reduce bad matches at lower MMRs
  - ⏰ FIGURE OUT HOW TO BALANCE LOW PING MATCHING WITH FAIREST MMR MATCHING
    - ⏰ High MMR/top competitive players are used to playing across oceans and continents
    - ⏰ Low MMR players just want to not fight the game
    - ⏰ Tune the matchmaker to prefer low ping at lower MMR at expense of MMR fairness? Default to strict MMR fairness higher up??? Is this fair?
  - ⏰ Match confirmation alert should be separate from match information display
    - ⏰ Players should have to confirm they are available to play before they can see any information about the match
- Scaling:
  - ⏰ Add extra API keys to handle Korean, Simplified Chinese, Spanish, Portugese, and German
- Setup:
  - ⏰ Make setup instructions less vague, e.g. people don't know what "user ID" means (but we cannot afford to use too many characters to explain it)

## PRE-RELEASE

- Account config:
  - ⏰ Create Paddle payment page
  - ⏰ Wire up Paddle 
  - ❌ Add columns to `players` table for managing subscription status
  - ⏰ Create a new `subscriptions` table to handle subscription status management

===

Hi all,

Before I go to bed tonight, I wanted to check in with everyone about the state of the ladder so far.

It's been just under 2 weeks since the alpha launch, and we have about 120 players who have played at least one game on the ladder. Those players have played a total of over 1700 games, or shy of 150 games per day.

In the grand scheme of StarCraft II, that's not much.

But the ladder alpha isn't defined by the number of people who play it — it's defined by the idea that even for all the inconveniences that a third-party StarCraft II ladder will never be able solve, people will still show up for the love of the game. People will play it because **SC: Evo Complete offers something that only the StarCraft community can build.**

The alpha phase of the ladder has been the most intense and rewarding experience I've had as a software engineer, and I'm grateful every day to be doing work that has a visible impact. Every single one of you who queued up for the ladder, reported bugs, or provided your thoughts on the feedback channels is not just simply an integral member of the community, but a co-contributor to what the ladder will become.

This project only works because real players show up and care. And you're one of them.

## What's Next

I'm going quieter on visible updates for a while. Not because development is slowing down, but because the next phase requires rebuilding the bot code from the ground up. It's the kind of work that isn't flashy — but it's essential. For that, I need to discontinue active work on the alpha. This means content and feature updates and bug fixes will be minimal.

The alpha proves that the ladder *can* exist. But the beta has to prove something more — that a third-party StarCraft II platform can be just as seamless and rewarding of an experience as anything Blizzard-official.

To do that, the foundation has to be right. The alpha codebase was built on sand, as a proof-of-concept: perfect for iteration, terrible for scale. The beta codebase will be set in bedrock: durable, resilient, and ready for anything the ladder will ever need.

## Roadmap for the Beta

Not only does the ladder code need to be rewritten, but the list of planned new features is ambitious.

The beta will serve as the testing grounds for the following:

- Full locale support for:
  - 🇺🇸 enUS
  - 🇰🇷 koKR
  - 🇨🇳 zhCN
  - 🇲🇽 esMX
  - 🇷🇺 ruRU
  - These language communities form the core of our playerbase.
- New gamemodes:
  - 2v2
  - 3v3
  - FFA
  - and other alternative gamemodes.
- Better matchmaking: more sensitive to wait times, concurrent player activity, and regional separation (especially at lower MMRs).
- Better match reporting: significantly more automation and far fewer manual reports. Match results will be processed from just one player uploading a file.
- Better sense of activity:
  - While current queue attempts in off-hours are shockingly high, most players leave quickly, missing each other by minutes.
  - The beta will feature tools to help players know when they can expect matches, without enabling sniping or dodging.
- Better analytics: expanding beyond basic Win/Loss/Draw into richer match history insights.
- Better admin tools: stronger monitoring and integrity systems to keep the ladder fair.
- And more.

The scope of this undertaking is the grandest of anything I've done before. Each new feature brings its own challenges, and the rebuild will likely take one to two months — perhaps more. But I'm doing it all with a clear goal: the beta cannot just be a hobby project. It needs to be built with all the attention and care that a serious, legitimate platform deserves.

## Thanks again for playing the ladder alpha.

In a few months, the ladder beta will be the star of the show, but it won't be alone. I can't share details yet, but there's more on the way. You won't want to miss it.

I'll see you all again soon with something worthy of a proper beta.

— HyperONE



====




