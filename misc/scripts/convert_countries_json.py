#!/usr/bin/env python3
"""
Script to convert countries.json from list format to dict format keyed by country code.
"""

import json
import sys
from pathlib import Path


def convert_countries_to_dict():
    """Convert countries.json from list to dict keyed by country code."""

    countries_file = Path("data/core/countries.json")

    if not countries_file.exists():
        print(f"Error: {countries_file} not found")
        sys.exit(1)

    # Read current list format
    with open(countries_file, "r") as f:
        countries_list = json.load(f)

    # Convert to dict keyed by country code
    countries_dict = {}
    for country in countries_list:
        code = country.pop("code")  # Remove code from object, use as key
        countries_dict[code] = country

    # Write back as dict
    with open(countries_file, "w") as f:
        json.dump(countries_dict, f, indent=2, ensure_ascii=False)
        f.write("\n")  # Add trailing newline

    print(f"✅ Converted {len(countries_list)} countries to dict format")
    print(f"📁 Updated {countries_file}")


if __name__ == "__main__":
    convert_countries_to_dict()
