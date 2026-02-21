## Basic Commands

- /leaderboard
- /profile
- /prune
    - It's nice but...do we even need this?
- /queue
    - Don't show match details until both players accept
    - Aborting a match before accepting incurs a timeout
    - Missing the deadline to accept a match incurs a timeout
    - Surrendering after match details are shown incurs penalties:
        - MMR loss (same as a normal loss)
        - Timeout
        - Surrender can only be done in <1-2 minutes
    - Timeout will be between 5-30 minutes
- /setcountry
- /setup
    - Include a more detailed setup guide this time
        - Players are consistently confused by the setup process
    - Rename a bunch of terminology
        - e.g. "player name", "player ID", "region/residency", etc.
- /termsofservice

## Admin Commands

- /admin adjust_mmr
- /admin ban
- /admin clear_queue
- /admin remove_queue
- /admin reset_aborts
    - Probably going to deprecate this
    - Aborts will cause MMR loss + no queueing for a time
- /admin unblock_queue
- /admin snapshot
- /admin match
- /admin resolve
- /admin player -> rename this to /admin profile
- /owner admin