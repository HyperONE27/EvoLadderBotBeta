from common.json_types import (
    Country,
    CrossTableData,
    Emote,
    GameModeData,
    Mod,
    Race,
    RegionData,
)


class Bot:
    def __init__(self) -> None:
        self._initialize_cache()
        self._load_data()

    def _initialize_cache(self) -> None:
        pass

    def _load_data(self) -> None:
        pass


class Cache:
    def __init__(self) -> None:
        # Static data from JSON files for lookups
        self.countries: dict[str, Country] = {}
        self.cross_table: CrossTableData = {
            "region_order": [],
            "mappings": {},
        }
        self.emotes: dict[str, Emote] = {}
        self.maps: dict[str, GameModeData] = {}
        self.mods: dict[str, Mod] = {}
        self.races: dict[str, Race] = {}
        self.regions: RegionData = {
            "geographic_regions": {},
            "game_servers": {},
            "game_regions": {},
        }

        # Localization
        # self.locales: dict[str, Locale] = {}
