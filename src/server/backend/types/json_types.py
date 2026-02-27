from typing import TypedDict


# countries.json data structure
# -----------------------------
class Country(TypedDict):
    code: str
    name: str
    common: bool


# cross_table.json data structure
# -------------------------------
class CrossTableData(TypedDict):
    region_order: list[str]
    mappings: dict[str, dict[str, str]]


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
    maps: dict[str, Map]


class GameModeData(TypedDict):
    seasons: dict[str, SeasonData]


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
    am_handles: list[str]
    am_artmod_handles: list[str]
    eu_handles: list[str]
    eu_artmod_handles: list[str]
    as_handles: list[str]
    as_artmod_handles: list[str]


# races.json data structure
# -------------------------
class Race(TypedDict):
    code: str
    name: str
    short_name: str
    aliases: list[str]
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
    geographic_regions: dict[str, GeographicRegion]
    game_servers: dict[str, GameServer]
    game_regions: dict[str, GameRegion]


# Complete data structure for all data/core/* .json files
# ------------------------------------------------------
class LoadedData(TypedDict):
    countries: dict[str, Country]
    cross_table: CrossTableData
    emotes: dict[str, Emote]
    maps: dict[str, GameModeData]
    mods: dict[str, Mod]
    races: dict[str, Race]
    regions: RegionData