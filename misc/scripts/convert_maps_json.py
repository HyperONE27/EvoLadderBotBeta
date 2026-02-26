#!/usr/bin/env python3
import json
from pathlib import Path


def convert_maps_to_dict():
    """Convert maps.json from season->array to season->dict keyed by short_name."""

    maps_file = Path("data/core/maps.json")

    # Read current structure
    with open(maps_file, "r") as f:
        current_data = json.load(f)

    # Convert each season from array to dict keyed by short_name
    converted_data = {}
    for season_name, maps_array in current_data.items():
        # Create dict keyed by short_name
        season_dict = {}
        for map_obj in maps_array:
            short_name = map_obj["short_name"]
            # Remove short_name from object since it becomes the key
            map_data = {k: v for k, v in map_obj.items() if k != "short_name"}
            season_dict[short_name] = map_data

        converted_data[season_name] = season_dict

    # Write back
    with open(maps_file, "w") as f:
        json.dump(converted_data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("✅ Converted maps.json to dict structure")
    print("📁 Maps now keyed by short_name within each season")


if __name__ == "__main__":
    convert_maps_to_dict()
