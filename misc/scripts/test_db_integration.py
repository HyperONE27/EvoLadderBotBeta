#!/usr/bin/env python3
"""
Integration test for the database reading pipeline.

Exercises the full path:
  secrets/.env -> DatabaseReader -> DataLoader -> StateManager

Run from the repository root:
    python misc_scripts/test_db_integration.py
"""

import sys
import time
import traceback
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

sys.path.insert(0, str(REPO_ROOT / "src"))

# ---------------------------------------------------------------------------
# Environment – must happen before any server.backend imports
# ---------------------------------------------------------------------------

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / "secrets" / ".env")

# ---------------------------------------------------------------------------
# Application imports (after path + env are ready)
# ---------------------------------------------------------------------------

import polars as pl  # noqa: E402

from server.backend.orchestrator.loader import DataLoader  # noqa: E402
from server.backend.orchestrator.state import StateManager  # noqa: E402

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

_results: list[tuple[str, str, str]] = []  # (status, name, detail)


def check(name: str, condition: bool, detail: str = "") -> None:
    """Record a pass/fail assertion."""
    status = PASS if condition else FAIL
    _results.append((status, name, detail))
    tag = f"  [{status}]"
    print(f"{tag:<10}{name}" + (f"  —  {detail}" if detail else ""))


def skip(name: str, reason: str = "") -> None:
    _results.append((SKIP, name, reason))
    print(f"  [SKIP]    {name}" + (f"  —  {reason}" if reason else ""))


def section(title: str) -> None:
    print(f"\n{'—' * 60}")
    print(f"  {title}")
    print(f"{'—' * 60}")


# ---------------------------------------------------------------------------
# Expected shapes
# ---------------------------------------------------------------------------

EXPECTED_JSON_KEYS = [
    "countries",
    "cross_table",
    "emotes",
    "maps",
    "mods",
    "races",
    "regions",
]

EXPECTED_DB_TABLES = [
    "players_df",
    "notifications_df",
    "events_df",
    "matches_1v1_df",
    "mmrs_1v1_df",
    "preferences_1v1_df",
    "replays_1v1_df",
]

# ---------------------------------------------------------------------------
# Test sections
# ---------------------------------------------------------------------------


def test_raw_connection() -> None:
    """
    Probe the Supabase connection directly, bypassing schema validation.

    Issues one raw SELECT per table using both the anon key and the
    service-role key so we can distinguish a bad connection from an RLS
    policy that silently filters all rows.
    """
    from server.backend.database.database import create_read_client, create_write_client

    section("Raw Connection Probe")

    # --- anon client ---
    try:
        anon = create_read_client()
        check("anon client created", True)
    except Exception as e:
        check("anon client created", False, str(e))
        return

    # --- service-role client ---
    try:
        svc = create_write_client()
        check("service-role client created", True)
    except Exception as e:
        check("service-role client created", False, str(e))
        svc = None

    table_names = [name.removesuffix("_df") for name in EXPECTED_DB_TABLES]

    print()
    print(f"  {'table':<22} {'anon rows':>10}  {'svc rows':>10}  note")
    print(f"  {'-'*22} {'-'*10}  {'-'*10}  {'-'*30}")

    for table_name in table_names:
        # anon key query (limit 1 — we only care if rows come back at all)
        try:
            anon_resp = anon.table(table_name).select("*").limit(1).execute()
            anon_count = len(anon_resp.data)
            anon_str = str(anon_count) if anon_count == 0 else f">={anon_count}"
        except Exception as e:
            anon_str = f"ERR: {e}"

        # service-role query
        svc_str = "n/a"
        if svc is not None:
            try:
                svc_resp = svc.table(table_name).select("*").limit(1).execute()
                svc_count = len(svc_resp.data)
                svc_str = str(svc_count) if svc_count == 0 else f">={svc_count}"
            except Exception as e:
                svc_str = f"ERR: {e}"

        # Diagnose the gap
        note = ""
        if anon_str == "0" and svc_str.startswith(">="):
            note = "RLS blocking anon key"
        elif anon_str == "0" and svc_str == "0":
            note = "table is empty"
        elif anon_str.startswith(">="):
            note = "OK"

        print(f"  {table_name:<22} {anon_str:>10}  {svc_str:>10}  {note}")

    print()


def test_env_vars() -> None:
    """Verify required environment variables are present."""
    import os

    section("Environment Variables")

    required = [
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "ADMINS",
    ]
    for var in required:
        value = os.getenv(var)
        check(f"{var} is set", bool(value), f"value={'<set>' if value else '<missing>'}")


def test_database_reader() -> dict[str, pl.DataFrame]:
    """Directly exercise DatabaseReader.load_all_tables()."""
    from server.backend.database.database import DatabaseReader

    section("DatabaseReader.load_all_tables()")

    tables: dict[str, pl.DataFrame] = {}
    try:
        reader = DatabaseReader()
        start = time.perf_counter()
        tables = reader.load_all_tables()
        elapsed = time.perf_counter() - start
        check("load_all_tables() completed without exception", True,
              f"elapsed={elapsed:.2f}s")
    except Exception:
        check("load_all_tables() completed without exception", False,
              traceback.format_exc().strip().splitlines()[-1])
        return tables

    expected_table_names = [name.removesuffix("_df") for name in EXPECTED_DB_TABLES]
    for table_name in expected_table_names:
        df = tables.get(table_name)
        present = df is not None
        check(f"table '{table_name}' returned", present)
        if present and isinstance(df, pl.DataFrame):
            check(
                f"table '{table_name}' has columns",
                len(df.columns) > 0,
                f"columns={df.columns}",
            )
            print(f"  [INFO]    table '{table_name}' row_count={len(df)}")

    return tables


def test_data_loader_state_manager() -> StateManager | None:
    """Run the full DataLoader -> StateManager pipeline."""
    section("DataLoader -> StateManager")

    # Reset the singleton so this script is re-entrant and self-contained.
    StateManager._instance = None
    state = StateManager()
    loader = DataLoader(data_dir=REPO_ROOT / "data" / "core")

    try:
        start = time.perf_counter()
        loader.populate_state_manager(state)
        elapsed = time.perf_counter() - start
        check("populate_state_manager() completed without exception", True,
              f"elapsed={elapsed:.2f}s")
    except Exception:
        check("populate_state_manager() completed without exception", False,
              traceback.format_exc().strip().splitlines()[-1])
        return None

    return state


def test_admins(state: StateManager) -> None:
    section("Admins")
    check("admins list is non-empty", len(state.admins) > 0,
          f"count={len(state.admins)}")
    for admin in state.admins:
        check(
            f"admin '{admin.get('name', '?')}' has required keys",
            all(k in admin for k in ("discord_id", "name", "role")),
        )


def _preview_json_value(value: Any, n: int = 3) -> str:
    """Return a short human-readable preview of a JSON-loaded value."""
    if isinstance(value, dict):
        keys = list(value.keys())[:n]
        pairs = {k: value[k] for k in keys}
        suffix = f", ... (+{len(value) - n} more)" if len(value) > n else ""
        return str(pairs) + suffix
    if isinstance(value, list):
        items = value[:n]
        suffix = f", ... (+{len(value) - n} more)" if len(value) > n else ""
        return str(items) + suffix
    return repr(value)


def test_json_data(state: StateManager) -> None:
    section("JSON Data (data/core/)")
    for key in EXPECTED_JSON_KEYS:
        value: Any = getattr(state, key, None)
        non_empty = value is not None and value not in ({}, [], "")
        check(f"{key} is loaded and non-empty", non_empty,
              f"type={type(value).__name__}")
        if non_empty:
            print(f"  [PREVIEW] {key}: {_preview_json_value(value)}")


def test_dataframes(state: StateManager) -> None:
    section("Polars DataFrames (database tables)")
    for attr in EXPECTED_DB_TABLES:
        df: Any = getattr(state, attr, None)
        is_df = isinstance(df, pl.DataFrame)
        check(f"{attr} is a pl.DataFrame", is_df,
              f"type={type(df).__name__}")
        if not is_df:
            continue
        check(f"{attr} has columns", len(df.columns) > 0,
              f"columns={df.columns}")
        print(f"  [INFO]    {attr} row_count={len(df)}")
        # Spot-check dtypes are not all Null/Unknown
        all_typed = all(dtype != pl.Null for dtype in df.dtypes)
        check(f"{attr} columns have concrete dtypes", all_typed)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 60)
    print("  DB Integration Test")
    print("=" * 60)

    test_env_vars()
    test_raw_connection()
    test_database_reader()

    state = test_data_loader_state_manager()
    if state is not None:
        test_admins(state)
        test_json_data(state)
        test_dataframes(state)

    # Summary
    total = len(_results)
    n_pass = sum(1 for s, _, _ in _results if s == PASS)
    n_fail = sum(1 for s, _, _ in _results if s == FAIL)
    n_skip = sum(1 for s, _, _ in _results if s == SKIP)

    print(f"\n{'=' * 60}")
    print(f"  Results: {n_pass}/{total} passed"
          + (f", {n_fail} failed" if n_fail else "")
          + (f", {n_skip} skipped" if n_skip else ""))
    print("=" * 60)

    if n_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
