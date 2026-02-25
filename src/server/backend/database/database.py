import polars as pl
from server.backend.config import DATABASE
from supabase import acreate_client
from typing import Dict

from server.backend.types.polars_dataframes import (
    PLAYERS_SCHEMA,
    NOTIFICATIONS_SCHEMA,
    EVENTS_SCHEMA,
    MATCHES_1V1_SCHEMA,
    MMRS_1V1_SCHEMA,
    PREFERENCES_1V1_SCHEMA,
    REPLAYS_1V1_SCHEMA,
)

# Connection functions
async def create_read_client():
    return await acreate_client(DATABASE["url"], DATABASE["anon_key"])

async def create_write_client():
    return await acreate_client(DATABASE["url"], DATABASE["service_role_key"])


class DatabaseReader:   
    def __init__(self):
        self.client = create_read_client()

    def load_all_tables(self) -> Dict[str, pl.DataFrame]:
        """Load all database tables into Polars DataFrames."""
        tables: Dict[str, pl.DataFrame] = {}
        
        tables_list = [
            "players",
            "notifications",
            "events",
            "matches_1v1",
            "mmrs_1v1",
            "preferences_1v1",
            "replays_1v1",
        ]

        for table_name in tables_list:
            tables[table_name] = self._load_table(table_name)
        
        return tables

    def _get_table_schema(self, table_name: str) -> Dict[str, pl.DataType]:
        """Get the Polars schema for a table."""
        schemas = {
            "players": PLAYERS_SCHEMA,
            "notifications": NOTIFICATIONS_SCHEMA,
            "events": EVENTS_SCHEMA,
            "matches_1v1": MATCHES_1V1_SCHEMA,
            "mmrs_1v1": MMRS_1V1_SCHEMA,
            "preferences_1v1": PREFERENCES_1V1_SCHEMA,
            "replays_1v1": REPLAYS_1V1_SCHEMA,
        }
        
        schema = schemas.get(table_name)
        if schema is None:
            raise ValueError(f"No schema defined for table: {table_name}")
        
        return schema

    def _load_table(self, table_name: str) -> pl.DataFrame:
        """Load a single table with strict schema validation."""

        try:
            response = self.client.table(table_name).select("*").execute()
            data = response.data
        except Exception as e:
            raise RuntimeError(f"Failed to query table '{table_name}': {e}")

        schema = self._get_table_schema(table_name)

        if not data:
            # Return a correctly-typed empty DataFrame so downstream code
            # can rely on the schema even when the table has no rows yet.
            return pl.DataFrame(schema=schema)

        return self._validate_schema(pl.DataFrame(data), schema, table_name)

    def _validate_schema(
        self,
        df: pl.DataFrame,
        expected_schema: Dict[str, pl.DataType],
        table_name: str,
    ) -> pl.DataFrame:
        """Validate DataFrame matches expected schema and return the cast DataFrame."""

        expected_columns = set(expected_schema.keys())
        actual_columns = set(df.columns)

        missing_columns = expected_columns - actual_columns
        extra_columns = actual_columns - expected_columns

        if missing_columns:
            raise ValueError(
                f"Table '{table_name}' missing expected columns: {missing_columns}"
            )

        if extra_columns:
            raise ValueError(
                f"Table '{table_name}' has unexpected columns: {extra_columns}"
            )

        try:
            return df.cast(expected_schema)
        except Exception as e:
            raise ValueError(f"Table '{table_name}' schema validation failed: {e}")


class DatabaseWriter:
    def __init__(self):
        self.client = create_write_client()

    # All write operations here
    
    def insert_player(self, data: Dict) -> Dict:
        pass