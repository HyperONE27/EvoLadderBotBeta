import json
import polars as pl
from pathlib import Path
from typing import Dict, Any

from server.backend.config import ADMINS
from server.backend.database.database import DatabaseReader
from server.backend.orchestrator.state_manager import StateManager
from server.backend.types.json_types import LoadedData

class DataLoader:
    """Loads all application data from JSON files and database."""
    
    def __init__(self, data_dir: Path = Path("data/core")):
        self.data_dir = data_dir
    
    def populate_state_manager(self, state_manager: StateManager) -> None:
        json_data = self._load_json_data()
        db_data = self._load_postgres_data()

        # Load admin data
        state_manager.admins = ADMINS

        # Load JSON data
        for key, value in json_data.items():
            setattr(state_manager, key, value)

        # Load Postgres data
        for table_name, df in db_data.items():
            setattr(state_manager, f"{table_name}_df", df)
    
    def _load_json_data(self) -> LoadedData:
        """Load all JSON data into typed structures."""
        return {
            "countries": self._load_json("countries.json"),
            "cross_table": self._load_json("cross_table.json"), 
            "emotes": self._load_json("emotes.json"),
            "maps": self._load_json("maps.json"),
            "mods": self._load_json("mods.json"),
            "races": self._load_json("races.json"),
            "regions": self._load_json("regions.json"),
        }
    
    def _load_postgres_data(self) -> Dict[str, pl.DataFrame]:
        """Load database tables into Polars DataFrames."""
        return DatabaseReader().load_all_tables()

    def _load_json(self, file_name: str) -> Dict[str, Any]:
        file_path = self.data_dir / file_name
        if not file_path.exists():
            raise FileNotFoundError(f"Required data file not found: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)