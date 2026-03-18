from backend.api.websocket import ConnectionManager
from backend.core.bootstrap import Backend

_backend: Backend | None = None
_ws_manager: ConnectionManager | None = None


def set_backend(app: Backend) -> None:
    global _backend
    _backend = app


def get_backend() -> Backend:
    if _backend is None:
        raise RuntimeError("Backend not initialized")
    return _backend


def set_ws_manager(manager: ConnectionManager) -> None:
    global _ws_manager
    _ws_manager = manager


def get_ws_manager() -> ConnectionManager:
    if _ws_manager is None:
        raise RuntimeError("WebSocket manager not initialized")
    return _ws_manager
