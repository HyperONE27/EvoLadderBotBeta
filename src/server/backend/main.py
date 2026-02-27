from server.backend.orchestrator.data_loader import DataLoader

# from server.backend.orchestrator.service_orchestrator import ServiceOrchestrator
from server.backend.orchestrator.state_manager import StateManager

# from server.backend.orchestrator.state_reader import StateReader
# from server.backend.orchestrator.transition_manager import TransitionManager
from server.backend.utils.country_utils import init_country_utils
from server.backend.utils.cross_table_utils import init_cross_table_utils
from server.backend.utils.emote_utils import init_emote_utils
from server.backend.utils.map_utils import init_map_utils
from server.backend.utils.mod_utils import init_mod_utils
from server.backend.utils.race_utils import init_race_utils
from server.backend.utils.region_utils import init_region_utils


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
        init_country_utils(self.state_manager)
        init_cross_table_utils(self.state_manager)
        init_emote_utils(self.state_manager)
        init_map_utils(self.state_manager)
        init_mod_utils(self.state_manager)
        init_race_utils(self.state_manager)
        init_region_utils(self.state_manager)

    def run(self) -> None:
        pass


def main() -> None:
    app = Application()
    app.run()


if __name__ == "__main__":
    main()
