from contextlib import asynccontextmanager
from fastapi import FastAPI

from backend.bootstrap import Application

_application: Application | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _application
    _application = Application()
    print("⚙️ [Backend] Application initialized.")
    yield
    print("🛑 [Backend] Application shutting down...")


app = FastAPI(lifespan=lifespan)


def get_application() -> Application:
    global _application
    if _application is None:
        raise RuntimeError("Application not initialized")
    return _application

# ----------------------------
# Include API routers
# (Keep this section here; 
# it breaks a circular import)
# ----------------------------


from backend.api.endpoints import router
app.include_router(router)