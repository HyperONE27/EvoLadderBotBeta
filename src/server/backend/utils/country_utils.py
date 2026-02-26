from typing import Dict
from server.backend.orchestrator.state_manager import StateManager
from server.backend.types.json_types import Country

ERROR_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------

def _check_initialized() -> None:
    if _state_manager is None:
        raise RuntimeError(ERROR_MODULE_NOT_INITIALIZED)

# ----------
# Public API
# ----------

def init_country_utils(state_manager: StateManager) -> None:
    """Initialize the country utils module."""
    global _state_manager
    _state_manager = state_manager

def get_countries() -> Dict[str, Country]:
    _check_initialized()
    return _state_manager.countries

def get_common_countries() -> Dict[str, Country]:
    """Get only common countries."""
    _check_initialized()
    return {code: country for code, country in get_countries().items() if country["common"]}

def get_country_by_code(code: str) -> Country | None:
    _check_initialized()
    return get_countries().get(code)

def get_country_by_name(name: str) -> Country | None:
    _check_initialized()
    return next((country for country in get_countries().values() if country["name"] == name), None)

def search_countries_by_partial_code(partial_code: str) -> Dict[str, Country]:
    """Search countries by partial code."""
    _check_initialized()
    return {code: country for code, country in get_countries().items() if partial_code.lower() in code.lower()}

def search_countries_by_partial_name(partial_name: str) -> Dict[str, Country]:
    """Search countries by partial name."""
    _check_initialized()
    return {code: country for code, country in get_countries().items() if partial_name.lower() in country["name"].lower()}