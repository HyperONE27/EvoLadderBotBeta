from server.backend.orchestrator.data_loader import DataLoader

# from server.backend.orchestrator.service_orchestrator import ServiceOrchestrator
from server.backend.orchestrator.state_manager import StateManager

# from server.backend.orchestrator.state_reader import StateReader
# from server.backend.orchestrator.transition_manager import TransitionManager
from server.backend.lookups.country_lookups import init_country_lookups
from server.backend.lookups.cross_table_lookups import init_cross_table_lookups
from server.backend.lookups.emote_lookups import init_emote_lookups
from server.backend.lookups.map_lookups import init_map_lookups
from server.backend.lookups.mod_lookups import init_mod_lookups
from server.backend.lookups.race_lookups import init_race_lookups
from server.backend.lookups.region_lookups import init_region_lookups


class Application:
    def __init__(self) -> None:
        # Initialize orchestrator components
        self.data_loader = DataLoader()
        # self.service_orchestrator = ServiceOrchestrator()
        self.state_manager = StateManager()
        # self.state_reader = StateReader()
        # self.transition_manager = TransitionManager()

        # Load application data
        self.data_loader.populate_state_manager(self.state_manager)

        # Initialize utility modules
        init_country_lookups(self.state_manager)
        init_cross_table_lookups(self.state_manager)
        init_emote_lookups(self.state_manager)
        init_map_lookups(self.state_manager)
        init_mod_lookups(self.state_manager)
        init_race_lookups(self.state_manager)
        init_region_lookups(self.state_manager)

    def run(self) -> None:
        pass


def main() -> None:
    app = Application()
    app.run()


if __name__ == "__main__":
    main()
