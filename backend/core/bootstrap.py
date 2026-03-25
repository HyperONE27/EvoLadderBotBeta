import asyncio
from concurrent.futures import ProcessPoolExecutor

import structlog

from backend.core.config import REPLAY_WORKER_PROCESSES
from backend.api.websocket import ConnectionManager
from backend.database.database import DatabaseWriter
from backend.database.storage import StorageWriter
from backend.lookups.admin_lookups import init_admin_lookups
from backend.lookups.match_1v1_lookups import init_match_1v1_lookups
from backend.lookups.mmr_1v1_lookups import init_mmr_1v1_lookups

from backend.lookups.notification_lookups import init_notification_lookups
from backend.lookups.player_lookups import init_player_lookups
from backend.lookups.preferences_1v1_lookups import init_preferences_1v1_lookups
from backend.lookups.preferences_2v2_lookups import init_preferences_2v2_lookups
from backend.lookups.replay_1v1_lookups import init_replay_1v1_lookups
from backend.orchestrator.orchestrator import Orchestrator
from backend.orchestrator.state import StateManager
from common.lookups.country_lookups import init_country_lookups
from common.lookups.cross_table_lookups import init_cross_table_lookups
from common.lookups.emote_lookups import init_emote_lookups

# from common.lookups.event_lookups import init_event_lookups
from common.lookups.map_lookups import init_map_lookups
from common.lookups.mod_lookups import init_mod_lookups
from common.lookups.race_lookups import init_race_lookups
from common.i18n import init_i18n
from common.loader import JSONLoader
from common.lookups.region_lookups import init_region_lookups

logger = structlog.get_logger(__name__)


def _noop() -> None:
    """No-op function submitted to the process pool for health checks.

    Must be a module-level function (not a lambda or closure) so it can
    be pickled and sent to the worker subprocess.
    """


class Backend:
    def __init__(self) -> None:
        self.process_pool = ProcessPoolExecutor(max_workers=REPLAY_WORKER_PROCESSES)
        self._initialize_orchestrator()
        self._initialize_lookups()

    async def ensure_pool_healthy(self) -> None:
        """Submit a no-op to the process pool and verify it completes.

        If the pool is broken (dead workers from a segfault in sc2reader,
        BrokenProcessPool, or timeout), replace it with a fresh one.
        """
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(self.process_pool, _noop),
                timeout=5.0,
            )
        except Exception:
            logger.critical(
                "ProcessPoolExecutor is broken — replacing with a fresh pool"
            )
            try:
                self.process_pool.shutdown(wait=False)
            except Exception:
                pass
            self.process_pool = ProcessPoolExecutor(max_workers=REPLAY_WORKER_PROCESSES)

    async def broadcast_queue_join_activity_if_needed(
        self,
        ws: ConnectionManager,
        joiner_uid: int,
        game_mode: str,
    ) -> None:
        """Notify opt-in subscribers (anonymous DMs) after a successful queue join."""

        payload = self.orchestrator.build_queue_join_activity_payload(
            joiner_uid,
            game_mode,
        )
        if not payload.get("notify_discord_uids"):
            return
        await ws.broadcast("queue_join_activity", payload)

    def _initialize_orchestrator(self) -> None:
        # Initialize orchestrator components
        self.state_manager = StateManager()
        self.db_writer = DatabaseWriter()
        self.storage_writer = StorageWriter()
        self.orchestrator = Orchestrator(self.state_manager, self.db_writer)

    def _initialize_lookups(self) -> None:
        init_i18n(JSONLoader().load_locale_data())
        modules = [
            init_admin_lookups,
            init_country_lookups,
            init_cross_table_lookups,
            init_emote_lookups,
            # init_event_lookups,
            init_map_lookups,
            init_match_1v1_lookups,
            init_mmr_1v1_lookups,
            init_mod_lookups,
            init_notification_lookups,
            init_player_lookups,
            init_preferences_1v1_lookups,
            init_preferences_2v2_lookups,
            init_race_lookups,
            init_region_lookups,
            init_replay_1v1_lookups,
        ]
        for init_func in modules:
            init_func(self.state_manager)
