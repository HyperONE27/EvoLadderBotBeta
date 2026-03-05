## Problems with the Alpha




## How The Beta Will Be Better




## Beta Planned Feature List



## Beta Architecture Overview

### 1. Discord Bot in Python (discord.py)

Not much should change from the alpha.

Just clean everything into:
- components
- button handlers
- slash command modules should be minimal
- split each admin command into a separate module

Data
- create localization data files
- make sure bot modules use localized strings instead of hardcoded ones
- 

Apparently:
- I was wrong about the 50 API calls/second limit - interaction responses don't count towards the limit
- This means my scaling potential is actually very strong

### 2. Ladder Backend in ~~Go~~ Python

No good replacement for simple columnar operations to Polars

### 3. Replay Parsing Microservice in Python (sc2reader)

- Just port the 


### 4. Remote PowerShell Service for BattleTags

- User calls a remote PowerShell script
- PowerShell script should:
  - Look through all subdirectories under "C:/Users/{stuff}/Documents/StarCraft II/Accounts/..."
  - Gather all toon handles (e.g. "1-S2-...", "2-S2-...", "3-S2-...")
  - 

===

ARCHITECTURE

# Server

## Database


## Backend

### Orchestrator
- DataLoader:
    - Runs when the backend processes launches
    - Handles the initialization of StateManager
- ServiceOrchestrator:
    - Coordinates stateless backend service calls
    - Chains calls into each other
- StateManager:
    - Owns all state
    - Built to be dumb: all data, no logic
- StateReader:
    - Handles all read operations on StateManager
- TransitionManager:
    - Handles all write operations on StateManager
    - Responsible for validating and applying all state changes


### Services

## Bot


===

CHECKLIST

❌⏰✅

- Database
    - Schema
    - Connection
    - Reader
    - Writer
    - Job Queue
- Backend
    - API
        - Schema
            - /countries/
            - 
            - /matches/
            - /players/
            - /
        - GET: Retrieve data from the server
            - 
        - POST: Create a new resource or submit data
            - 
        - PUT: Replace an existing resource/data
            - 
        - DELETE: Remove a resource/data
            - 
    - Orchestrator
        - DataLoader
        - ServiceOrchestrator
        - StateManager
        - StateReader
        - TransitionManager
            - Add initialization
            - Set up 
    - Algorithms
        - 
        - 
        - 
        - 
        - 
        - 
    - Lookups
        - ✅ country_lookups.py
        - ✅ cross_table_lookups.py
        - ✅ emote_lookups.py
        - ✅ map_lookups.py
        - ✅ mod_lookups.py
        - ✅ race_lookups.py
        - ✅ region_lookups.py
- Bot
    - Config
        - Intents
        - Graceful Shutdown
    - Commands
        - Admin Commands
            - /owner admin
            - /admin ban
            - /admin match
            - /admin mmr
            - /admin snapshot
            - /admin status
        - User Commands
            - /help
            - /leaderboard
            - /profile
            - /prune
            - /queue
            - /setcountry
            - /setup
    - Components
        - Embeds
        - Views
        - Buttons
        - Dropdowns
        - Modals

- End-to-End Flows
    - Bot Command
    - HTTP API Request to Backend
    - HTTP API Request received by Backend
    - HTTP API Request serialized by Backend
    - ServiceOrchestrator processing:
        - ServiceOrchestrator calls the relevant StateReader/service concerns
        - ServiceOrchestrator calls the relevant TransitionManager concerns
    - ServiceOrchestrator completes and returns
    - HTTP response sent to bot middleware

- Experiment Claude-Generated Modules to clean up later
    - src/server/backend/services/matchmaker_service.py
    - src/server/backend/utils/*
        - map_utils.py

===

❌⏰✅❓

- Old Files to Convert:
    - ⏰ src/backend/
        - ❌ adapters/*
            - The need for these is completely antiquated
                - We are no longer juggling both SQLite and PostgreSQL
        - ⏰ services/
            - ❌ admin_service.py
            - ❌ app_context.py
                - Necessary persistent data handled in backend/.../main.py
                - Most backend modules are no longer instantiated as singletons
            - ❌ base_config_service.py
                - Lookups no longer inherit from a base class
            - ❌ cache_service.py
                - Deprecated; lookup data handled by state.py
            - ⏰ command_guard_service.py
                - Needs to exist in some form
                - backend/orchestrator/ now contains authorization.py
            - ✅❓ countries_service.py
                - Replaced by country_lookup.py
            - ✅❓ data_access_service.py
                - Replaced by orchestrator/state/reader model
            - leaderboard_service.py
            - ⏰ load_monitor.py
                - Maybe useful?
            - ❌ localization_service.py
                - This is mostly a frontend concern
                - Retrieving the user's locale preference might belong in backend
            - ✅❓ maps_service.py
                - Replaced by map_lookup.py
            - match_completion_service.py
            - matchmaking_service.py
                - Replaced by 
            - ❌ memory_monitor.py
                - Use Railway instead
            - ✅ mmr_service.py
                - Replaced by mmr_1v1_lookup.py and ratings.py
            - ✅❓ mods_service.py
                - Replaced by map_lookup.py
            - notification_service.py
            - ⏰ performance_service.py
                - Might be useful
            - ⏰ process_pool_health.py
                - Might be useful
            - ✅❓ races_service.py
                - Replaced by race_lookup.py
            - ranking_service.py
            - ✅❓ regions_service.py
                - Replaced by cross_table_lookup.py and region_lookup.py
            - replay_job_queue.py
            - replay_parsing_timeout.py
            - ✅❓ replay_service.py
                - Definitely need this
            - ⏰ storage_service.py
                - 
            - ✅❓ user_info_service.py
                - Being replaced by player_lookup.py
            - validation_service.py
                - 
    - src/bot/
        - commands/
        - components/
        - utils/

===

Describe what the workflows of each command are, from the perspective of the backend.

Don't worry for now what the bot middleware needs to do.

Isolate concerns based on what the backend must fetch, update, and coordinate.
(Preferably in chronological order.)

- Admin Commands
    - /owner admin {discord_uid}
        - Read: Retrieve the current list of admins and see if the user is there
        - Write: Toggle the user's admin status
    - /owner mmr
    - /owner profile
        - Read: Retrieve the user's information
        - Write: Update the user's information
    - /admin ban
        - Read: Retrieve the user's ban status
        - Write: Toggle the user's ban status
    - /admin match
        - Read: Retrieve the match information and replays
    - /admin profile {discord_uid}
        - Read: Retrieve the user's information
    - /admin resolve {match_id} {match_result}
        - Read: Retrieve the match information
        - Write: Update the match information
    - /admin snapshot
        - Read: Retrieve the current state of the application
    - /admin status {discord_uid}
        - Read: Retrieve the current state of the user
        - Write: Update the current state of the user
- User Commands
    - /help
        - Read: Retrieve /help information
    - /leaderboard
        - Read: Retrieve leaderboard information
    - /profile
        - Read: Retrieve user information
            - Discord UID, Discord username, player name, alt player names
            - BattleTag
            - Nationality, location
            - Statistics (overall + by race)
                - Total games + W-L-D record
                - Win rates
                - Last Played
            - Account Status
                - ToS accepted
                - Setup completed
                - Abort counts (deprecated)
    - /prune
    - /queue
        - Read: 
    - /setcountry
        - Read
    - /setup
        - 

===

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