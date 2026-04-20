import asyncio
import time

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from backend.api.dependencies import (
    get_backend,
    get_ws_manager,
    set_backend,
    set_ws_manager,
)
from backend.api.endpoints import router
from backend.api.websocket import ConnectionManager
from backend.core.bootstrap import Backend
from backend.core.config import CONFIRMATION_TIMEOUT

from common.config import QUEUE_NOTIFY_SWEEP_INTERVAL_SECONDS
from common.logging.config import configure_structlog

logger = structlog.get_logger(__name__)

ws_manager = ConnectionManager()


async def _matchmaker_loop() -> None:
    """Run matchmaking waves at the top of every minute."""
    ws = get_ws_manager()
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
                enriched = backend.orchestrator.enrich_match_with_ranks(dict(match))
                await ws.broadcast("match_found", enriched)

                # Schedule a confirmation timeout for this match.
                asyncio.create_task(
                    _confirmation_timeout(match_id, CONFIRMATION_TIMEOUT)
                )

        except Exception:
            logger.exception("Matchmaker wave failed")


async def _matchmaker_loop_2v2() -> None:
    """Run 2v2 matchmaking waves at the top of every minute."""
    ws = get_ws_manager()
    while True:
        now = time.time()
        next_top = (now // 60 + 1) * 60
        await asyncio.sleep(next_top - now)
        try:
            backend = get_backend()
            created_matches = backend.orchestrator.run_matchmaking_wave_2v2()

            for match in created_matches:
                match_id = match["id"]

                enriched = backend.orchestrator.enrich_match_2v2_with_ranks(dict(match))
                await ws.broadcast("match_found", {"game_mode": "2v2", **enriched})

                asyncio.create_task(
                    _confirmation_timeout_2v2(match_id, CONFIRMATION_TIMEOUT)
                )

        except Exception:
            logger.exception("2v2 matchmaker wave failed")


async def _confirmation_timeout_2v2(match_id: int, timeout: int) -> None:
    """Wait for the confirmation window, then handle timeout if not yet confirmed."""
    await asyncio.sleep(timeout)
    try:
        backend = get_backend()
        ws = get_ws_manager()

        if backend.orchestrator.is_match_2v2_confirmed(match_id):
            return

        success, _ = backend.orchestrator.handle_confirmation_timeout_2v2(match_id)
        if success:
            match = backend.orchestrator.get_match_2v2(match_id)
            if match is not None:
                enriched = backend.orchestrator.enrich_match_2v2_with_ranks(dict(match))
                await ws.broadcast("match_abandoned", {"game_mode": "2v2", **enriched})

    except Exception:
        logger.exception(
            f"2v2 confirmation timeout handling failed for match #{match_id}"
        )


async def _activity_notifier_sweep_loop() -> None:
    """Re-ping subscribers whose cooldown elapsed while someone is still queued.

    Complements the immediate ``queue_join_activity`` broadcast on queue-join:
    if Alice sits in queue longer than Bob's notify cooldown, Bob gets pinged
    again. DB-side ``last_sent`` tracking prevents spam.
    """
    ws = get_ws_manager()
    while True:
        await asyncio.sleep(QUEUE_NOTIFY_SWEEP_INTERVAL_SECONDS)
        try:
            backend = get_backend()
            for game_mode, queue in (
                ("1v1", backend.state_manager.queue_1v1),
                ("2v2", backend.state_manager.queue_2v2),
            ):
                if not queue:
                    continue
                longest_waiter = min(queue, key=lambda e: e["joined_at"])
                joiner_uid = int(longest_waiter["discord_uid"])
                await backend.broadcast_queue_join_activity_if_needed(
                    ws, joiner_uid, game_mode
                )
        except Exception:
            logger.exception("Activity-notifier sweep failed")


async def _confirmation_timeout(match_id: int, timeout: int) -> None:
    """Wait for the confirmation window, then handle timeout if not yet confirmed."""
    await asyncio.sleep(timeout)
    try:
        backend = get_backend()
        ws = get_ws_manager()

        if backend.orchestrator.is_match_confirmed(match_id):
            return

        success, message = backend.orchestrator.handle_confirmation_timeout(match_id)
        if success:
            match = backend.orchestrator.get_match_1v1(match_id)
            if match is not None:
                enriched = backend.orchestrator.enrich_match_with_ranks(dict(match))
                await ws.broadcast("match_abandoned", enriched)

    except Exception:
        logger.exception(f"Confirmation timeout handling failed for match #{match_id}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_structlog(service_name="backend")

    backend = Backend()
    set_backend(backend)
    set_ws_manager(ws_manager)
    backend.orchestrator.reset_all_player_statuses()
    backend.orchestrator.log_event(
        {
            "discord_uid": 1,  # backend sentinel
            "event_type": "system_event",
            "action": "startup",
            "event_data": {},
        }
    )
    logger.info("[Backend] Backend initialized.")

    matchmaker_task = asyncio.create_task(_matchmaker_loop())
    matchmaker_task_2v2 = asyncio.create_task(_matchmaker_loop_2v2())
    activity_notifier_task = asyncio.create_task(_activity_notifier_sweep_loop())

    yield

    matchmaker_task.cancel()
    matchmaker_task_2v2.cancel()
    activity_notifier_task.cancel()
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
