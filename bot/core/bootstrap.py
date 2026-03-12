from common.json_types import (
    Country,
    CrossTableData,
    Emote,
    GameModeData,
    Mod,
    Race,
    RegionData,
)
from common.loader import JSONLoader


class Bot:
    def __init__(self) -> None:
        self._initialize_cache()

    def _initialize_cache(self) -> None:
        self.cache = Cache()


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

        self._populate_json_data()
        self._populate_locale_data()

    def _populate_json_data(self) -> None:
        json_data = JSONLoader().load_core_data()

        for key, value in json_data.items():
            if not hasattr(self, key):
                raise ValueError(f"Cache does not have attribute {key}")
            setattr(self, key, value)

    def _populate_locale_data(self) -> None:
        pass
