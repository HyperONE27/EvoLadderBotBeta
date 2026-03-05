from server.backend.orchestrator.loader import DataLoader

# from server.backend.orchestrator.orchestrator import ServiceOrchestrator
from server.backend.orchestrator.state import StateManager

# from server.backend.orchestrator.reader import StateReader
# from server.backend.orchestrator.transitions import TransitionManager
from server.backend.lookups.country_lookups import init_country_lookups
from server.backend.lookups.cross_table_lookups import init_cross_table_lookups
from server.backend.lookups.emote_lookups import init_emote_lookups

# from server.backend.lookups.event_lookups import init_event_lookups
from server.backend.lookups.map_lookups import init_map_lookups
from server.backend.lookups.match_1v1_lookups import init_match_1v1_lookups
from server.backend.lookups.mmr_1v1_lookups import init_mmr_1v1_lookups
from server.backend.lookups.mod_lookups import init_mod_lookups

# from server.backend.lookups.notification_lookups import init_notification_lookups
from server.backend.lookups.player_lookups import init_player_lookups

from server.backend.lookups.preferences_1v1_lookups import init_preferences_1v1_lookups
from server.backend.lookups.race_lookups import init_race_lookups
from server.backend.lookups.region_lookups import init_region_lookups
from server.backend.lookups.replay_1v1_lookups import init_replay_1v1_lookups


class Application:
    def __init__(self) -> None:
        self._initialize_orchestrator()
        self._load_data()
        self._initialize_lookups()

    def _initialize_orchestrator(self) -> None:
        # Initialize orchestrator components
        self.data_loader = DataLoader()
        # self.service_orchestrator = ServiceOrchestrator()
        self.state_manager = StateManager()
        # self.state_reader = StateReader()
        # self.transition_manager = TransitionManager()

    def _load_data(self) -> None:
        # Load application data
        self.data_loader.populate_state_manager(self.state_manager)

    def _initialize_lookups(self) -> None:
        modules = [
            init_country_lookups,
            init_cross_table_lookups,
            init_emote_lookups,
            # init_event_lookups,
            init_map_lookups,
            init_match_1v1_lookups,
            init_mmr_1v1_lookups,
            init_mod_lookups,
            # init_notification_lookups,
            init_player_lookups,
            init_preferences_1v1_lookups,
            init_race_lookups,
            init_region_lookups,
            init_replay_1v1_lookups,
        ]
        for init_func in modules:
            init_func(self.state_manager)

    def run(self) -> None:
        pass
