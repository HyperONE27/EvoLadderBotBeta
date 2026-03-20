import asyncio
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

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
from common.lookups.region_lookups import init_region_lookups


class Backend:
    def __init__(self) -> None:
        self.process_pool = ProcessPoolExecutor(max_workers=REPLAY_WORKER_PROCESSES)
        self._queue_notify_lock = asyncio.Lock()
        self._queue_notify_last_sent: dict[int, datetime] = {}
        self._initialize_orchestrator()
        self._initialize_lookups()

    async def broadcast_queue_join_activity_if_needed(
        self,
        ws: ConnectionManager,
        joiner_uid: int,
        game_mode: str,
    ) -> None:
        """Notify opt-in subscribers (anonymous DMs) after a successful queue join."""

        async with self._queue_notify_lock:
            payload = self.orchestrator.build_queue_join_activity_payload(
                joiner_uid,
                game_mode,
                self._queue_notify_last_sent,
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
            init_race_lookups,
            init_region_lookups,
            init_replay_1v1_lookups,
        ]
        for init_func in modules:
            init_func(self.state_manager)
