import asyncio
import time

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from backend.api.dependencies import get_backend, set_backend
from backend.api.endpoints import router
from backend.api.websocket import ConnectionManager
from backend.core.bootstrap import Backend
from backend.core.config import QUEUE

from common.logging.config import configure_structlog

logger = structlog.get_logger(__name__)

ws_manager = ConnectionManager()


async def _matchmaker_loop() -> None:
    """Run matchmaking waves at the top of every minute."""
    while True:
        now = time.time()
        next_top = (now // 60 + 1) * 60
        await asyncio.sleep(next_top - now)
        try:
            backend = get_backend()
            created_matches = backend.orchestrator.run_matchmaking_wave()

            for match in created_matches:
                match_id = match["id"]

                # Broadcast match_found to the bot.
                await ws_manager.broadcast("match_found", dict(match))

                # Schedule a confirmation timeout for this match.
                asyncio.create_task(
                    _confirmation_timeout(match_id, QUEUE["confirmation_timeout"])
                )

        except Exception:
            logger.exception("Matchmaker wave failed")


async def _confirmation_timeout(match_id: int, timeout: int) -> None:
    """Wait for the confirmation window, then handle timeout if not yet confirmed."""
    await asyncio.sleep(timeout)
    try:
        backend = get_backend()

        if backend.orchestrator.is_match_confirmed(match_id):
            return

        success, message = backend.orchestrator.handle_confirmation_timeout(match_id)
        if success:
            match = backend.orchestrator.get_match_1v1(match_id)
            if match is not None:
                await ws_manager.broadcast("match_abandoned", dict(match))

    except Exception:
        logger.exception(f"Confirmation timeout handling failed for match #{match_id}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_structlog(service_name="backend")

    backend = Backend()
    set_backend(backend)
    backend.orchestrator.reset_all_player_statuses()
    logger.info("[Backend] Backend initialized.")

    matchmaker_task = asyncio.create_task(_matchmaker_loop())

    yield

    matchmaker_task.cancel()
    backend.process_pool.shutdown(wait=False)
    logger.info("[Backend] Backend shutting down...")


app = FastAPI(lifespan=lifespan)
app.include_router(router)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
