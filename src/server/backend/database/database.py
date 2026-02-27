import polars as pl
from supabase import create_client, Client

from server.backend.config import DATABASE
from server.backend.types.polars_dataframes import TABLE_SCHEMAS


# Connection functions
def create_read_client() -> Client:
    return create_client(DATABASE["url"], DATABASE["anon_key"])


def create_write_client() -> Client:
    return create_client(DATABASE["url"], DATABASE["service_role_key"])


class DatabaseReader:
    def __init__(self) -> None:
        self.client: Client = create_read_client()

    def load_all_tables(self) -> dict[str, pl.DataFrame]:
        """Load all database tables into Polars DataFrames."""
        tables: dict[str, pl.DataFrame] = {}

        for table_name in TABLE_SCHEMAS.keys():
            tables[table_name] = self._load_table(table_name)

        return tables

    def _get_table_schema(self, table_name: str) -> dict[str, pl.DataType]:
        """Get the Polars schema for a table."""
        return TABLE_SCHEMAS.get(table_name)

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
        expected_schema: dict[str, pl.DataType],
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
    def __init__(self) -> None:
        self.client: Client = create_write_client()

    # All write operations here
