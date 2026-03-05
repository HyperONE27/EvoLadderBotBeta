from backend.bootstrap import Application

_application: Application | None = None


def set_application(app: Application) -> None:
    global _application
    _application = app


def get_application() -> Application:
    if _application is None:
        raise RuntimeError("Application not initialized")
    return _application
