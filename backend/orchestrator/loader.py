import json
import polars as pl
from pathlib import Path
from typing import Any, cast

from backend.config import ADMINS
from backend.database.database import DatabaseReader
from backend.orchestrator.state import StateManager
from backend.domain_types.json_types import CrossTableData, LoadedData, RegionData


class DataLoader:
    """Loads all application data from JSON files and database."""

    def __init__(
        self,
        data_dir: Path = Path(
            Path(__file__).resolve().parent.parent.parent / "data" / "core"
        ),
    ) -> None:
        self.data_dir: Path = data_dir

    def populate_state_manager(self, state_manager: StateManager) -> None:
        json_data = self._load_json_data()
        db_data = self._load_postgres_data()

        # Load admin data
        state_manager.admins = ADMINS

        # Load JSON data
        for key, value in json_data.items():
            if not hasattr(state_manager, key):
                raise ValueError(f"StateManager does not have attribute {key}")
            setattr(state_manager, key, value)

        # Load Postgres data
        for table_name, df in db_data.items():
            if not hasattr(state_manager, f"{table_name}_df"):
                raise ValueError(
                    f"StateManager does not have attribute {table_name}_df"
                )
            setattr(state_manager, f"{table_name}_df", df)

    def _load_json_data(self) -> LoadedData:
        """Load all JSON data into typed structures."""
        return {
            "countries": self._load_json("countries.json"),
            "cross_table": cast(CrossTableData, self._load_json("cross_table.json")),
            "emotes": self._load_json("emotes.json"),
            "maps": self._load_json("maps.json"),
            "mods": self._load_json("mods.json"),
            "races": self._load_json("races.json"),
            "regions": cast(RegionData, self._load_json("regions.json")),
        }

    def _load_postgres_data(self) -> dict[str, pl.DataFrame]:
        """Load database tables into Polars DataFrames."""
        return DatabaseReader().load_all_tables()

    def _load_json(self, file_name: str) -> dict[str, Any]:
        file_path = self.data_dir / file_name
        if not file_path.exists():
            raise FileNotFoundError(f"Required data file not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            return cast(dict[str, Any], json.load(f))
