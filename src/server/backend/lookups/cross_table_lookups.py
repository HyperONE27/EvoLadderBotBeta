from server.backend.orchestrator.state import StateManager

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------


def _get_state_manager() -> StateManager:
    if _state_manager is None:
        raise RuntimeError(_MODULE_NOT_INITIALIZED)
    return _state_manager


def _get_region_order() -> list[str]:
    return _get_state_manager().cross_table["region_order"]


def _get_mappings() -> dict[str, dict[str, str]]:
    return _get_state_manager().cross_table["mappings"]


def _sort_region_pair(region_1: str, region_2: str) -> tuple[str, str]:
    region_order = _get_region_order()
    if region_1 not in region_order or region_2 not in region_order:
        raise ValueError(f"Region {region_1} or {region_2} not found in region_order")
    if region_order.index(region_1) <= region_order.index(region_2):
        return region_1, region_2
    return region_2, region_1


# ----------
# Public API
# ----------


def init_cross_table_lookups(state_manager: StateManager) -> None:
    global _state_manager
    _state_manager = state_manager


def get_game_server_from_region_pair(region_1: str, region_2: str) -> str:
    region_1, region_2 = _sort_region_pair(region_1, region_2)
    mappings = _get_mappings()
    return mappings[region_1][region_2]
