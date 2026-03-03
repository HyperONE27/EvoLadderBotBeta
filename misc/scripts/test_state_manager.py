#!/usr/bin/env python3
"""
Comprehensive test for StateManager data loading and validation.

Combines database integration testing with thorough JSON data shape validation
against json_types.py type definitions.

Run from the repository root:
    python misc/scripts/test_state_manager.py
"""

import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, get_type_hints

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
from server.backend.types.json_types import (  # noqa: E402
    Country, CrossTableData, Emote, GameModeData, LoadedData, Map,
    Mod, Race, RegionData, SeasonData, GeographicRegion, GameServer,
    GameRegion
)

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
    """Record a skip."""
    _results.append((SKIP, name, reason))
    print(f"  [SKIP]    {name}" + (f"  —  {reason}" if reason else ""))


def section(title: str) -> None:
    print(f"\n{'—' * 60}")
    print(f"  {title}")
    print(f"{'—' * 60}")


# ---------------------------------------------------------------------------
# Expected shapes and constants
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
# JSON Type Validation Functions
# ---------------------------------------------------------------------------


def validate_typed_dict(data: Dict[str, Any], typed_dict_class: Any, context: str = "") -> List[str]:
    """
    Validate that a dictionary matches a TypedDict class structure.

    Returns a list of validation errors (empty if valid).
    """
    errors = []
    type_hints = get_type_hints(typed_dict_class)

    # Check required keys
    for key, expected_type in type_hints.items():
        if key not in data:
            errors.append(f"{context}: Missing required key '{key}'")
            continue

        # Basic type checking
        value = data[key]
        if expected_type == str:
            if not isinstance(value, str):
                errors.append(f"{context}.{key}: Expected str, got {type(value).__name__}")
        elif expected_type == bool:
            if not isinstance(value, bool):
                errors.append(f"{context}.{key}: Expected bool, got {type(value).__name__}")
        elif expected_type == int:
            if not isinstance(value, int):
                errors.append(f"{context}.{key}: Expected int, got {type(value).__name__}")
        elif hasattr(expected_type, '__origin__'):  # Generic types like List[str], Dict[str, str]
            origin = expected_type.__origin__
            if origin == list:
                if not isinstance(value, list):
                    errors.append(f"{context}.{key}: Expected list, got {type(value).__name__}")
                elif expected_type.__args__ and len(expected_type.__args__) > 0:
                    # Check list element types
                    element_type = expected_type.__args__[0]
                    for i, item in enumerate(value):
                        if element_type == str and not isinstance(item, str):
                            errors.append(f"{context}.{key}[{i}]: Expected str, got {type(item).__name__}")
            elif origin == dict:
                if not isinstance(value, dict):
                    errors.append(f"{context}.{key}: Expected dict, got {type(value).__name__}")

    return errors


def validate_country(country_data: Dict[str, Any], country_code: str) -> List[str]:
    """Validate a single Country entry."""
    return validate_typed_dict(country_data, Country, f"countries.{country_code}")


def validate_emote(emote_data: Dict[str, Any], emote_name: str) -> List[str]:
    """Validate a single Emote entry."""
    return validate_typed_dict(emote_data, Emote, f"emotes.{emote_name}")


def validate_map(map_data: Dict[str, Any], season: str, map_key: str) -> List[str]:
    """Validate a single Map entry."""
    return validate_typed_dict(map_data, Map, f"maps.{season}.{map_key}")


def validate_mod(mod_data: Dict[str, Any], mod_code: str) -> List[str]:
    """Validate a single Mod entry."""
    return validate_typed_dict(mod_data, Mod, f"mods.{mod_code}")


def validate_race(race_data: Dict[str, Any], race_code: str) -> List[str]:
    """Validate a single Race entry."""
    return validate_typed_dict(race_data, Race, f"races.{race_code}")


def validate_geographic_region(region_data: Dict[str, Any], region_code: str) -> List[str]:
    """Validate a single GeographicRegion entry."""
    return validate_typed_dict(region_data, GeographicRegion, f"regions.geographic_regions.{region_code}")


def validate_game_server(server_data: Dict[str, Any], server_code: str) -> List[str]:
    """Validate a single GameServer entry."""
    return validate_typed_dict(server_data, GameServer, f"regions.game_servers.{server_code}")


def validate_game_region(region_data: Dict[str, Any], region_code: str) -> List[str]:
    """Validate a single GameRegion entry."""
    return validate_typed_dict(region_data, GameRegion, f"regions.game_regions.{region_code}")


def validate_cross_table(cross_table_data: Dict[str, Any]) -> List[str]:
    """Validate CrossTableData structure."""
    errors = validate_typed_dict(cross_table_data, CrossTableData, "cross_table")

    # Additional validation for mappings structure
    if "mappings" in cross_table_data and isinstance(cross_table_data["mappings"], dict):
        for key, mapping in cross_table_data["mappings"].items():
            if not isinstance(mapping, dict):
                errors.append(f"cross_table.mappings.{key}: Expected dict, got {type(mapping).__name__}")
            else:
                # Check that all values in mapping are strings
                for sub_key, sub_value in mapping.items():
                    if not isinstance(sub_value, str):
                        errors.append(f"cross_table.mappings.{key}.{sub_key}: Expected str, got {type(sub_value).__name__}")

    return errors


def validate_maps_structure(maps_data: Dict[str, Any]) -> List[str]:
    """Validate the entire maps structure."""
    errors = []

    if not isinstance(maps_data, dict):
        return ["maps: Expected dict at top level"]

    # Check if this matches the expected GameModeData structure or the raw JSON structure
    # The actual JSON structure is: {"1v1": {"season_alpha": {"map_name": {...}}}}
    # But the typed structure expects: {"maps": {"1v1": {"seasons": {"season_alpha": {"maps": {...}}}}}

    # First check if it's the expected typed structure
    has_typed_structure = True
    for game_mode, game_mode_data in maps_data.items():
        if not isinstance(game_mode_data, dict):
            has_typed_structure = False
            break
        if "seasons" not in game_mode_data:
            has_typed_structure = False
            break

    if has_typed_structure:
        # Validate as GameModeData structure
        for game_mode, game_mode_data in maps_data.items():
            if not isinstance(game_mode_data, dict):
                errors.append(f"maps.{game_mode}: Expected dict, got {type(game_mode_data).__name__}")
                continue

            seasons = game_mode_data["seasons"]
            if not isinstance(seasons, dict):
                errors.append(f"maps.{game_mode}.seasons: Expected dict, got {type(seasons).__name__}")
                continue

            for season_code, season_data in seasons.items():
                if not isinstance(season_data, dict):
                    errors.append(f"maps.{game_mode}.seasons.{season_code}: Expected dict, got {type(season_data).__name__}")
                    continue

                if "maps" not in season_data:
                    errors.append(f"maps.{game_mode}.seasons.{season_code}: Missing 'maps' key")
                    continue

                maps_dict = season_data["maps"]
                if not isinstance(maps_dict, dict):
                    errors.append(f"maps.{game_mode}.seasons.{season_code}.maps: Expected dict, got {type(maps_dict).__name__}")
                    continue

                # Validate each map (skip placeholders with empty short_name)
                for map_key, map_data in maps_dict.items():
                    if isinstance(map_data, dict) and map_data.get("short_name", "").strip() == "":
                        # Skip placeholder entries
                        continue
                    errors.extend(validate_map(map_data, f"{game_mode}.{season_code}", map_key))
    else:
        # Validate as raw JSON structure: {"1v1": {"season_alpha": {"map_name": {...}}}}
        for game_mode, seasons_data in maps_data.items():
            if not isinstance(seasons_data, dict):
                errors.append(f"maps.{game_mode}: Expected dict, got {type(seasons_data).__name__}")
                continue

            for season_code, maps_dict in seasons_data.items():
                if not isinstance(maps_dict, dict):
                    errors.append(f"maps.{game_mode}.{season_code}: Expected dict, got {type(maps_dict).__name__}")
                    continue

                # Validate each map (skip placeholders with empty short_name)
                for map_key, map_data in maps_dict.items():
                    if isinstance(map_data, dict) and map_data.get("short_name", "").strip() == "":
                        # Skip placeholder entries
                        continue
                    errors.extend(validate_map(map_data, f"{game_mode}.{season_code}", map_key))

    return errors


def validate_regions_structure(regions_data: Dict[str, Any]) -> List[str]:
    """Validate the entire regions structure."""
    errors = validate_typed_dict(regions_data, RegionData, "regions")

    # Validate nested structures
    if "geographic_regions" in regions_data and isinstance(regions_data["geographic_regions"], dict):
        for code, region_data in regions_data["geographic_regions"].items():
            errors.extend(validate_geographic_region(region_data, code))

    if "game_servers" in regions_data and isinstance(regions_data["game_servers"], dict):
        for code, server_data in regions_data["game_servers"].items():
            errors.extend(validate_game_server(server_data, code))

    if "game_regions" in regions_data and isinstance(regions_data["game_regions"], dict):
        for code, region_data in regions_data["game_regions"].items():
            errors.extend(validate_game_region(region_data, code))

    return errors


def validate_json_data_integrity(state: StateManager) -> None:
    """Fine-grained validation of JSON data integrity and consistency."""
    section("JSON Data Integrity Validation")

    integrity_errors = []

    # Validate country data integrity
    integrity_errors.extend(validate_countries_integrity(state.countries))

    # Validate emote data integrity
    integrity_errors.extend(validate_emotes_integrity(state.emotes))

    # Validate map data integrity
    integrity_errors.extend(validate_maps_integrity(state.maps))

    # Validate mod data integrity
    integrity_errors.extend(validate_mods_integrity(state.mods))

    # Validate race data integrity
    integrity_errors.extend(validate_races_integrity(state.races))

    # Validate region data integrity
    integrity_errors.extend(validate_regions_integrity(state.regions))

    # Cross-reference validations
    integrity_errors.extend(validate_cross_references(state))

    # Report results
    if integrity_errors:
        check("All JSON data passes integrity checks", False, f"{len(integrity_errors)} integrity errors")
        for error in integrity_errors[:10]:  # Show first 10 errors
            print(f"  [ERROR]   {error}")
        if len(integrity_errors) > 10:
            print(f"  [ERROR]   ... and {len(integrity_errors) - 10} more errors")
    else:
        check("All JSON data passes integrity checks", True)


def validate_countries_integrity(countries: Dict[str, Any]) -> List[str]:
    """Validate country data integrity."""
    errors = []

    # Check country codes are valid ISO codes (2-3 uppercase letters)
    for code, country_data in countries.items():
        if not isinstance(code, str) or not code.isupper() or not (2 <= len(code) <= 3):
            errors.append(f"countries.{code}: Invalid country code format (should be 2-3 uppercase letters)")

        # Check common field is boolean
        if "common" in country_data and not isinstance(country_data["common"], bool):
            errors.append(f"countries.{code}.common: Expected boolean, got {type(country_data['common']).__name__}")

    # Check for duplicate names
    names = {}
    for code, country_data in countries.items():
        name = country_data.get("name", "")
        if name in names:
            errors.append(f"countries: Duplicate country name '{name}' (codes: {names[name]}, {code})")
        else:
            names[name] = code

    return errors


def validate_emotes_integrity(emotes: Dict[str, Any]) -> List[str]:
    """Validate emote data integrity."""
    errors = []

    # Check short_name uniqueness and format
    short_names = set()
    for emote_name, emote_data in emotes.items():
        short_name = emote_data.get("short_name", "")
        if short_name in short_names:
            errors.append(f"emotes: Duplicate short_name '{short_name}'")
        short_names.add(short_name)

        # Check short_name format (typically 2-3 characters)
        if not isinstance(short_name, str) or len(short_name) < 1 or len(short_name) > 5:
            errors.append(f"emotes.{emote_name}.short_name: Invalid short_name length (1-5 chars expected)")

        # Check markdown format (should contain Discord emoji syntax)
        markdown = emote_data.get("markdown", "")
        if not isinstance(markdown, str) or not (markdown.startswith('<') and '>' in markdown):
            errors.append(f"emotes.{emote_name}.markdown: Invalid Discord emoji format")

    return errors


def validate_maps_integrity(maps: Dict[str, Any]) -> List[str]:
    """Validate map data integrity."""
    errors = []

    valid_games = {'bw', 'sc2'}

    # Collect all maps for cross-validation
    all_maps = {}
    short_names = set()

    for game_mode, seasons_data in maps.items():
        if not isinstance(seasons_data, dict):
            continue

        for season_code, maps_dict in seasons_data.items():
            if not isinstance(maps_dict, dict):
                continue

            for map_key, map_data in maps_dict.items():
                if isinstance(map_data, dict) and map_data.get("short_name", "").strip():
                    # Validate individual map
                    map_errors = validate_single_map_integrity(map_data, f"{game_mode}.{season_code}.{map_key}", valid_games)
                    errors.extend(map_errors)

                    # Collect for uniqueness checks
                    short_name = map_data.get("short_name", "")
                    if short_name:
                        if short_name in short_names:
                            errors.append(f"maps: Duplicate short_name '{short_name}' across seasons")
                        short_names.add(short_name)

                        all_maps[short_name] = map_data

    # Validate map references in cross_table (if it exists)
    # This would be done in cross-reference validation

    return errors


def validate_single_map_integrity(map_data: Dict[str, Any], context: str, valid_games: set) -> List[str]:
    """Validate a single map's integrity."""
    errors = []

    # Check game field
    game = map_data.get("game", "")
    if game not in valid_games:
        errors.append(f"{context}.game: Invalid game '{game}' (expected one of {valid_games})")

    # Check link formats
    for region in ['am', 'eu', 'as']:
        link_key = f"{region}_link"
        link = map_data.get(link_key, "")
        if link and not isinstance(link, str):
            errors.append(f"{context}.{link_key}: Expected string, got {type(link).__name__}")
        elif link and not (link.startswith('battlenet:://') or link.startswith('http')):
            errors.append(f"{context}.{link_key}: Invalid link format")

    # Check short_name format (should be reasonable length)
    short_name = map_data.get("short_name", "")
    if len(short_name) < 2 or len(short_name) > 50:
        errors.append(f"{context}.short_name: Invalid length ({len(short_name)} chars, expected 2-50)")

    # Check author field
    author = map_data.get("author", "")
    if len(author) < 2 or len(author) > 100:
        errors.append(f"{context}.author: Invalid author length ({len(author)} chars, expected 2-100)")

    return errors


def validate_mods_integrity(mods: Dict[str, Any]) -> List[str]:
    """Validate mod data integrity."""
    errors = []

    for mod_code, mod_data in mods.items():
        # Check code format (should be reasonable)
        if len(mod_code) < 1 or len(mod_code) > 20:
            errors.append(f"mods.{mod_code}: Invalid code length ({len(mod_code)} chars)")

        # Check handle arrays
        for region in ['am', 'eu', 'as']:
            handles_key = f"{region}_handles"
            handles = mod_data.get(handles_key, [])
            if not isinstance(handles, list):
                errors.append(f"mods.{mod_code}.{handles_key}: Expected list, got {type(handles).__name__}")
            else:
                for i, handle in enumerate(handles):
                    if not isinstance(handle, str):
                        errors.append(f"mods.{mod_code}.{handles_key}[{i}]: Expected string, got {type(handle).__name__}")
                    elif not handle.startswith('http'):
                        errors.append(f"mods.{mod_code}.{handles_key}[{i}]: Invalid URL format")

    return errors


def validate_races_integrity(races: Dict[str, Any]) -> List[str]:
    """Validate race data integrity."""
    errors = []

    valid_race_codes = {'bw_terran', 'bw_zerg', 'bw_protoss', 'sc2_terran', 'sc2_zerg', 'sc2_protoss'}

    for race_code, race_data in races.items():
        # Check code is in expected set
        if race_code not in valid_race_codes:
            errors.append(f"races.{race_code}: Unexpected race code")

        # Check boolean fields
        for bool_field in ['is_bw_race', 'is_sc2_race']:
            value = race_data.get(bool_field, None)
            if not isinstance(value, bool):
                errors.append(f"races.{race_code}.{bool_field}: Expected boolean, got {type(value).__name__}")

        # Check aliases is list of strings
        aliases = race_data.get("aliases", [])
        if not isinstance(aliases, list):
            errors.append(f"races.{race_code}.aliases: Expected list, got {type(aliases).__name__}")
        else:
            for i, alias in enumerate(aliases):
                if not isinstance(alias, str):
                    errors.append(f"races.{race_code}.aliases[{i}]: Expected string, got {type(alias).__name__}")

        # Check short_name format (typically 2 chars like 'T1', 'Z1', 'P1')
        short_name = race_data.get("short_name", "")
        if len(short_name) != 2 or not (short_name[0].isalpha() and short_name[1].isdigit()):
            errors.append(f"races.{race_code}.short_name: Invalid format '{short_name}' (expected like 'T1')")

    return errors


def validate_regions_integrity(regions: Dict[str, Any]) -> List[str]:
    """Validate region data integrity."""
    errors = []

    # Validate geographic regions
    if "geographic_regions" in regions:
        geo_regions = regions["geographic_regions"]
        for code, region_data in geo_regions.items():
            # Check globe_emote_code references exist in emotes
            emote_code = region_data.get("globe_emote_code", "")
            if not emote_code:
                errors.append(f"regions.geographic_regions.{code}: Missing globe_emote_code")

    # Validate game servers
    if "game_servers" in regions:
        game_servers = regions["game_servers"]
        for code, server_data in game_servers.items():
            # Check game_region_code references exist
            region_code = server_data.get("game_region_code", "")
            if "game_regions" in regions and region_code not in regions["game_regions"]:
                errors.append(f"regions.game_servers.{code}: game_region_code '{region_code}' not found in game_regions")

    return errors


def validate_cross_references(state: StateManager) -> List[str]:
    """Validate cross-references between different JSON datasets."""
    errors = []

    # Build lookup maps for validation
    game_servers_by_code = {}
    if hasattr(state, 'regions') and 'game_servers' in state.regions:
        for server_code, server_data in state.regions['game_servers'].items():
            game_servers_by_code[server_code] = server_data

    # Check if cross_table region_order references exist in geographic_regions
    if hasattr(state, 'cross_table') and 'region_order' in state.cross_table:
        region_order = state.cross_table['region_order']
        geographic_regions = state.regions.get('geographic_regions', {})

        for region_code in region_order:
            if region_code not in geographic_regions:
                errors.append(f"cross_table.region_order: '{region_code}' not found in regions.geographic_regions")

    # Check if cross_table mappings reference valid regions and servers
    if hasattr(state, 'cross_table') and 'mappings' in state.cross_table:
        mappings = state.cross_table['mappings']
        geographic_regions = state.regions.get('geographic_regions', {})

        for from_region, mapping in mappings.items():
            if from_region not in geographic_regions:
                errors.append(f"cross_table.mappings: source region '{from_region}' not found in regions.geographic_regions")

            for to_region, server_code in mapping.items():
                if to_region not in geographic_regions:
                    errors.append(f"cross_table.mappings.{from_region}: target region '{to_region}' not found in regions.geographic_regions")

                # Check server_code exists in game_servers
                if server_code not in game_servers_by_code:
                    errors.append(f"cross_table.mappings.{from_region}.{to_region}: server code '{server_code}' not found in regions.game_servers")

    return errors


def validate_json_data_types(state: StateManager) -> None:
    """Validate all JSON data against json_types.py type definitions."""
    section("JSON Data Type Validation")

    all_errors = []

    # Validate countries
    for country_code, country_data in state.countries.items():
        all_errors.extend(validate_country(country_data, country_code))

    # Validate cross_table
    all_errors.extend(validate_cross_table(state.cross_table))

    # Validate emotes
    for emote_name, emote_data in state.emotes.items():
        all_errors.extend(validate_emote(emote_data, emote_name))

    # Validate maps
    all_errors.extend(validate_maps_structure(state.maps))

    # Validate mods
    for mod_code, mod_data in state.mods.items():
        all_errors.extend(validate_mod(mod_data, mod_code))

    # Validate races
    for race_code, race_data in state.races.items():
        all_errors.extend(validate_race(race_data, race_code))

    # Validate regions
    all_errors.extend(validate_regions_structure(state.regions))

    # Report results
    if all_errors:
        check("All JSON data conforms to type definitions", False, f"{len(all_errors)} validation errors")
        for error in all_errors[:10]:  # Show first 10 errors
            print(f"  [ERROR]   {error}")
        if len(all_errors) > 10:
            print(f"  [ERROR]   ... and {len(all_errors) - 10} more errors")
    else:
        check("All JSON data conforms to type definitions", True)


# ---------------------------------------------------------------------------
# Test sections (adapted from test_db_integration.py)
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
    print("  StateManager Integration & Type Validation Test")
    print("=" * 60)

    test_env_vars()
    test_raw_connection()
    test_database_reader()

    state = test_data_loader_state_manager()
    if state is not None:
        test_admins(state)
        test_json_data(state)
        test_dataframes(state)
        validate_json_data_types(state)
        validate_json_data_integrity(state)

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