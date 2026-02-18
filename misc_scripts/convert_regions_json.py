#!/usr/bin/env python3
import json
from pathlib import Path


def convert_regions_to_dict():
    """Convert regions.json arrays to dicts keyed by code."""

    regions_file = Path("data/core/regions.json")

    # Read current structure
    with open(regions_file, "r") as f:
        current_data = json.load(f)

    # Convert each array to dict keyed by code
    converted_data = {}
    for section_name, items_array in current_data.items():
        if isinstance(items_array, list):
            # Convert array to dict keyed by code
            section_dict = {}
            for item in items_array:
                code = item["code"]
                # Remove code from object since it becomes the key
                item_data = {k: v for k, v in item.items() if k != "code"}
                section_dict[code] = item_data
            converted_data[section_name] = section_dict
        else:
            # Keep non-array values as-is
            converted_data[section_name] = items_array

    # Write back
    with open(regions_file, "w") as f:
        json.dump(converted_data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("✅ Converted regions.json to dict structure")
    print("📁 All region/server lookups now O(1)")


if __name__ == "__main__":
    convert_regions_to_dict()
