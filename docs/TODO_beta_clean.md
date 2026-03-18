What remains?

❌⏰✅

# FINISH BY PRE-BETA

- ⏰ /leaderboard is completely unimplemented
    - 1/7/21/21/21/21/8% splits
    - Ordinal rank calculation
    - Store in Leaderboard1v1 in StateManager
- ⏰ /profile looks weird
- ⏰ /profile doesn't contain full T/W/L/D (win-rate %) statistics by race and aggregated
- ⏰ Generally the UI is messed up everywhere
    - Especially /snapshot
    - ⏰ Holy shit fix this
- ⏰ Implement the infrastructure
    - of what??? I forgot
- ✅ mmrs_1v1 W/L/D/T game counts desync from matches_1v1 when a match gets resolved more than once
    - Admin resolutions need to force a recalculation of the affected mmrs_1v1 rows
- ⏰ Make sure visibility is solid
    - Maybe some more admin/owner commands
        - Directly reading DataFrame rows
- ⏰ Fix mypy error suppressions and underlying issues
- ⏰ Add some kind of health check and automatic resurrection for:
    - replay parsing process pool
    - DataFrames
        - write-through guarantees writes hit the DB
        - but not that DFs might not silently corrupt...(?)
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
- ⏰ Add unit tests

# FINISH DURING PRE-BETA

- Need some way for players to see who is online
    - Activity notifier when someone queues
    - Analytics charts showing when are peak hours
- Fill out localization strings
    - Localizers will do this slowly
- Add 2v2 and FFA gamemodes

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