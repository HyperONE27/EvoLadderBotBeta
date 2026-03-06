import json
from pathlib import Path
from typing import Any, cast

from common.json_types import CrossTableData, LoadedData, RegionData


class JSONLoader:
    """Loads all application data from JSON files."""

    def __init__(
        self,
        data_dir: Path = Path(Path(__file__).resolve().parent.parent / "data" / "core"),
    ) -> None:
        self.data_dir: Path = data_dir

    def load_core_data(self) -> LoadedData:
        """Loads all core JSON data into typed structures."""
        return {
            "countries": self._load_json("countries.json"),
            "cross_table": cast(
                CrossTableData,
                self._load_json("cross_table.json"),
            ),
            "emotes": self._load_json("emotes.json"),
            "maps": self._load_json("maps.json"),
            "mods": self._load_json("mods.json"),
            "races": self._load_json("races.json"),
            "regions": cast(
                RegionData,
                self._load_json("regions.json"),
            ),
        }

    def load_locale_data(self, file_name: str) -> None:
        """Loads all locale JSON data into typed structures."""
        pass

    def _load_json(self, file_name: str) -> dict[str, Any]:
        file_path = self.data_dir / file_name
        if not file_path.exists():
            raise FileNotFoundError(f"Required JSON file not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            return cast(dict[str, Any], json.load(f))
