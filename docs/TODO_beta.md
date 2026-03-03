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
    - Services
        - 
        - 
        - 
        - 
        - 
        - 
        - 
        - 
        - 
    - Utilities
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

❌⏰✅

- Old Files to Convert:
    - ⏰ src/backend/
        - ❌ adapters/
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
            - command_guard_service.py
            - countries_service.py
            - data_access_service.py
            - leaderboard_service.py
            - load_monitor.py
            - localization_service.py
            - maps_service.py
            - match_completion_service.py
            - matchmaking_service.py
            - memory_monitor.py
            - mmr_service.py
            - mods_service.py
            - notification_service.py
            - performance_service.py
            - process_pool_health.py
            - races_service.py
            - ranking_service.py
            - regions_service.py
            - replay_job_queue.py
            - replay_parsing_timeout.py
            - replay_service.py
            - storage_service.py
            - user_info_service.py
            - validation_service.py
    - src/bot/
        - commands/
        - components/
        - utils/
