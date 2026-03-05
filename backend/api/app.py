from contextlib import asynccontextmanager
from fastapi import FastAPI

from server.backend.bootstrap import Application

_application: Application | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _application
    _application = Application()
    yield


app = FastAPI(lifespan=lifespan)


def get_application() -> Application:
    global _application
    if _application is None:
        raise RuntimeError("Application not initialized")
    return _application
