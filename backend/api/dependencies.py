from backend.bootstrap import Backend

_backend: Backend | None = None


def set_backend(app: Backend) -> None:
    global _backend
    _backend = app


def get_backend() -> Backend:
    if _backend is None:
        raise RuntimeError("Backend not initialized")
    return _backend
