"""
Denormalizes JSON data files by injecting each entry's dictionary key
as a named field (e.g. "code" or "name") at the front of the object.

Transforms entries like:
    "US": {"name": "United States", "common": true}
Into:
    "US": {"code": "US", "name": "United States", "common": true}

Files processed:
    - countries.json:  key → "code"
    - emotes.json:     key → "name"
    - mods.json:       key → "code"
    - races.json:      key → "code"
    - regions.json:    geographic_regions[*] key → "code"
                       game_servers[*]       key → "code"
                       game_regions[*]       key → "code"
"""

import json
from pathlib import Path

DATA_DIR = Path("data/core")


def inject_key(data: dict, field_name: str) -> dict:
    """Return a new dict where each value has the key injected as field_name first."""
    return {
        key: {field_name: key, **value}
        for key, value in data.items()
    }


def process_flat(filename: str, field_name: str) -> None:
    """Denormalize a flat top-level dict."""
    path = DATA_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    denormalized = inject_key(data, field_name)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(denormalized, f, indent=4, ensure_ascii=False)

    print(f"Denormalized {filename} (key → '{field_name}')")


def process_regions() -> None:
    """Denormalize the nested geographic_regions, game_servers, and game_regions."""
    path = DATA_DIR / "regions.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["geographic_regions"] = inject_key(data["geographic_regions"], "code")
    data["game_servers"] = inject_key(data["game_servers"], "code")
    data["game_regions"] = inject_key(data["game_regions"], "code")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print("Denormalized regions.json (geographic_regions, game_servers, game_regions → 'code')")


def process_maps() -> None:
    """Denormalize the nested maps within each season."""
    path = DATA_DIR / "maps.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    denormalized = {
        season_key: inject_key(season_data, "short_name")
        for season_key, season_data in data.items()
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(denormalized, f, indent=4, ensure_ascii=False)

    print("Denormalized maps.json (map keys → 'short_name' per season)")


if __name__ == "__main__":
    process_flat("countries.json", "code")
    process_flat("emotes.json", "name")
    process_flat("mods.json", "code")
    process_flat("races.json", "code")
    process_regions()
    process_maps()
    print("Done.")
