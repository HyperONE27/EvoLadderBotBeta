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
