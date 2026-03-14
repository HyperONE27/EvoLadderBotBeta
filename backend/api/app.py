import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI

from backend.api.dependencies import set_backend
from backend.api.endpoints import router
from backend.core.bootstrap import Backend

from common.logging.config import configure_structlog

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_structlog(service_name="backend")

    backend = Backend()
    set_backend(backend)
    logger.info("⚙️ [Backend] Backend initialized.")
    yield
    logger.info("🛑 [Backend] Backend shutting down...")


app = FastAPI(lifespan=lifespan)
app.include_router(router)
