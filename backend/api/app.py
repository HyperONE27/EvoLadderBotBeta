from contextlib import asynccontextmanager
from fastapi import FastAPI

from backend.api.dependencies import set_backend
from backend.api.endpoints import router
from backend.bootstrap import Backend


@asynccontextmanager
async def lifespan(app: FastAPI):
    backend = Backend()
    set_backend(backend)
    print("⚙️ [Backend] Backend initialized.")
    yield
    print("🛑 [Backend] Backend shutting down...")


app = FastAPI(lifespan=lifespan)
app.include_router(router)
