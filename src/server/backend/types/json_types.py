from typing import List, Dict, TypedDict


# countries.json data structure
# -----------------------------
class Country(TypedDict):
    code: str
    name: str
    common: bool


# cross_table.json data structure
# -------------------------------
class CrossTableData(TypedDict):
    region_order: List[str]
    mappings: Dict[str, Dict[str, str]]


# emotes.json data structure
# --------------------------
class Emote(TypedDict):
    name: str
    short_name: str
    markdown: str


# maps.json data structure
# ------------------------
class Map(TypedDict):
    short_name: str
    name: str
    author: str
    am_link: str
    eu_link: str
    as_link: str
    game: str


class SeasonData(TypedDict):
    maps: Dict[str, Map]


class GameModeData(TypedDict):
    seasons: Dict[str, SeasonData]


# mods.json data structure
# ------------------------
class Mod(TypedDict):
    code: str
    name: str
    short_name: str
    author: str
    am_link: str
    eu_link: str
    as_link: str
    am_handles: List[str]
    am_artmod_handles: List[str]
    eu_handles: List[str]
    eu_artmod_handles: List[str]
    as_handles: List[str]
    as_artmod_handles: List[str]


# races.json data structure
# -------------------------
class Race(TypedDict):
    code: str
    name: str
    short_name: str
    aliases: List[str]
    is_bw_race: bool
    is_sc2_race: bool


# regions.json data structure
# ---------------------------
class GeographicRegion(TypedDict):
    code: str
    name: str
    globe_emote_code: str


class GameServer(TypedDict):
    code: str
    name: str
    short_name: str
    game_region_code: str


class GameRegion(TypedDict):
    code: str
    name: str


class RegionData(TypedDict):
    geographic_regions: Dict[str, GeographicRegion]
    game_servers: Dict[str, GameServer]
    game_regions: Dict[str, GameRegion]


# Complete data structure for all data/core/* .json files
# ------------------------------------------------------
class LoadedData(TypedDict):
    countries: Dict[str, Country]
    cross_table: CrossTableData
    emotes: Dict[str, Emote]
    maps: Dict[str, GameModeData]
    mods: Dict[str, Mod]
    races: Dict[str, Race]
    regions: RegionData