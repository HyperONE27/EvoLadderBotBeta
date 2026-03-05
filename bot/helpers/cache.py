from typing import TypedDict


class Cache(TypedDict):
    countries: dict[str, dict[str, str | bool]]
    cross_table: dict[str, list[str] | dict[str, dict[str, str]]]
    emotes: dict[str, dict[str, str]]
    maps: dict[str, str]
    mods: dict[str, str]
    races: dict[str, dict]
    regions: dict[str, str]
