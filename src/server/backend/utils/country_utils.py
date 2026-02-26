from typing import Dict
from server.backend.orchestrator.state_manager import StateManager
from server.backend.types.json_types import Country

ERROR_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------

def _get_country_by_code(code: str) -> Country | None:
    """Get country by code."""
    if _state_manager is None:
        raise RuntimeError(ERROR_MODULE_NOT_INITIALIZED)
    return _state_manager.countries.get(code)

# ----------
# Public API
# ----------

def init_country_utils(state_manager: StateManager) -> None:
    """Initialize the country utils module."""
    global _state_manager
    _state_manager = state_manager

def get_countries() -> Dict[str, Country]:
    """Get all countries."""
    if _state_manager is None:
        raise RuntimeError(ERROR_MODULE_NOT_INITIALIZED)
    return _state_manager.countries

def get_common_countries() -> Dict[str, Country]:
    """Get only common countries."""
    if _state_manager is None:
        raise RuntimeError(ERROR_MODULE_NOT_INITIALIZED)
    return {code: country for code, country in get_countries().items() if country["common"]}

def get_country_name_by_code(code: str) -> str | None:
    """Get country name by code."""
    if _state_manager is None:
        raise RuntimeError(ERROR_MODULE_NOT_INITIALIZED)
    country = _get_country_by_code(code)
    return country["name"] if country else None

def get_country_code_by_name(name: str) -> str | None:
    """Get country code by name."""
    if _state_manager is None:
        raise RuntimeError(ERROR_MODULE_NOT_INITIALIZED)
    return next((code for code, country in get_countries().items() if country["name"] == name), None)

def search_countries_by_partial_name(partial_name: str) -> Dict[str, Country]:
    """Search countries by partial name."""
    if _state_manager is None:
        raise RuntimeError(ERROR_MODULE_NOT_INITIALIZED)
    return {code: country for code, country in get_countries().items() if partial_name.lower() in country["name"].lower()}