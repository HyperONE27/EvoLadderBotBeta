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
from common.lookups.country_lookups import init_country_lookups
from common.lookups.cross_table_lookups import init_cross_table_lookups
from common.lookups.emote_lookups import init_emote_lookups
from common.lookups.map_lookups import init_map_lookups
from common.lookups.mod_lookups import init_mod_lookups
from common.lookups.race_lookups import init_race_lookups
from common.lookups.region_lookups import init_region_lookups


class Bot:
    def __init__(self) -> None:
        self._initialize_cache()
        self._initialize_lookups()

    def _initialize_cache(self) -> None:
        self.cache = Cache()

    def _initialize_lookups(self) -> None:
        modules = [
            init_country_lookups,
            init_cross_table_lookups,
            init_emote_lookups,
            init_map_lookups,
            init_mod_lookups,
            init_race_lookups,
            init_region_lookups,
        ]
        for init_func in modules:
            init_func(self.cache)


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
