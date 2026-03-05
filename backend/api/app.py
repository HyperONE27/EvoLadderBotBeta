from contextlib import asynccontextmanager
from fastapi import FastAPI

from backend.api.dependencies import set_application
from backend.api.endpoints import router
from backend.bootstrap import Application


@asynccontextmanager
async def lifespan(app: FastAPI):
    application = Application()
    set_application(application)
    print("⚙️ [Backend] Application initialized.")
    yield
    print("🛑 [Backend] Application shutting down...")


app = FastAPI(lifespan=lifespan)
app.include_router(router)
