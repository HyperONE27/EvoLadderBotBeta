#!/usr/bin/env python3
import json
import glob
from pathlib import Path


def format_json_files():
    for json_file in glob.glob("data/core/*.json"):
        path = Path(json_file)

        # Read and parse
        with open(path, "r") as f:
            data = json.load(f)

        # Write back with consistent formatting
        with open(path, "w") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.write("\n")  # Add trailing newline


if __name__ == "__main__":
    format_json_files()
