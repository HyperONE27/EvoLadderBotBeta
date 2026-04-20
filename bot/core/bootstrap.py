from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import discord

from common.json_types import (
    Country,
    CrossTableData,
    Emote,
    GameModeData,
    Mod,
    Race,
    RegionData,
)
from common.i18n import init_i18n
from common.loader import JSONLoader
from common.lookups.country_lookups import init_country_lookups
from common.lookups.cross_table_lookups import init_cross_table_lookups
from common.lookups.emote_lookups import init_emote_lookups
from common.lookups.map_lookups import init_map_lookups
from common.lookups.mod_lookups import init_mod_lookups
from common.lookups.race_lookups import init_race_lookups
from common.lookups.region_lookups import init_region_lookups


class Bot:
    def __init__(self) -> None:
        self._initialize_cache()
        self._initialize_lookups()

    def _initialize_cache(self) -> None:
        self.cache = Cache()

    def _initialize_lookups(self) -> None:
        modules = [
            init_country_lookups,
            init_cross_table_lookups,
            init_emote_lookups,
            init_map_lookups,
            init_mod_lookups,
            init_race_lookups,
            init_region_lookups,
        ]
        for init_func in modules:
            init_func(self.cache)


class Cache:
    def __init__(self) -> None:
        # Static data from JSON files for lookups
        self.countries: dict[str, Country] = {}
        self.cross_table: CrossTableData = {
            "region_order": [],
            "mappings": {},
            "pings": {},
        }
        self.emotes: dict[str, Emote] = {}
        self.maps: dict[str, GameModeData] = {}
        self.mods: dict[str, Mod] = {}
        self.races: dict[str, Race] = {}
        self.regions: RegionData = {
            "geographic_regions": {},
            "game_servers": {},
            "game_regions": {},
        }

        # Localization
        # self.locales: dict[str, Locale] = {}

        # --- Runtime tracking (populated by the WS listener and on_message handler) ---

        # Maps discord_uid → the QueueSearchingEmbed message so ws_listener can
        # edit it when a match is found and strip the cancel button.
        self.active_searching_messages: dict[int, "discord.Message"] = {}

        # Maps discord_uid → QueueSearchingView so the heartbeat can be stopped.
        self.active_searching_views: dict[int, object] = {}

        # Maps discord_uid → {"match_data": dict, "p1_info": dict|None,
        # "p2_info": dict|None} while the player is in an active match.
        # Cleared when the match ends (any terminal WS event).
        self.active_match_info: dict[int, dict] = {}

        # Maps discord_uid → the MatchFoundEmbed message (confirm/abort buttons) so the
        # WS listener can strip those buttons if the match ends before both confirm.
        self.active_match_found_messages: dict[int, "discord.Message"] = {}

        # Maps discord_uid → the MatchInfoEmbed message so the replay handler
        # can update the embed and enable the report dropdown after a successful upload.
        self.active_match_messages: dict[int, "discord.Message"] = {}

        # Leaderboard data pushed from the backend via WS. Each entry is a dict
        # matching the LeaderboardEntry1v1 TypedDict shape.
        self.leaderboard_1v1: list[dict] = []
        self.leaderboard_2v2: list[dict] = []

        # Per-player locale preference (discord_uid → locale code, e.g. "enUS").
        # Populated when a player completes /setup or when their profile is loaded.
        self.player_locales: dict[int, str] = {}

        # Per-player setup preset data (discord_uid → player dict from backend).
        # Populated by check_if_banned from the GET /players/{uid} response so that
        # TermsOfServiceSetupView can pre-populate the setup modal without a second
        # backend round-trip.
        self.player_presets: dict[int, dict[str, Any]] = {}

        # UIDs that have already been sent the onboarding flow this session.
        # Prevents re-sending to existing players with completed_setup=false
        # on every DM. Lost on restart (harmless — they just get it again).
        self.onboarding_sent_uids: set[int] = set()

        # Per-player notification preset data (discord_uid → NotificationsOut dict).
        # Populated at the start of /setup so the notification step can pre-select
        # existing preferences without an HTTP call mid-flow.
        self.notification_presets: dict[int, dict[str, Any]] = {}

        # The single status-embed message in ACTIVITY_STATS_CHANNEL_ID (may be None
        # if the channel isn't configured or discovery is still in progress).
        self.activity_status_message: "discord.Message | None" = None

        self._populate_json_data()
        self._populate_locale_data()

    def _populate_json_data(self) -> None:
        json_data = JSONLoader().load_core_data()

        for key, value in json_data.items():
            if not hasattr(self, key):
                raise ValueError(f"Cache does not have attribute {key}")
            setattr(self, key, value)

    def _populate_locale_data(self) -> None:
        locales = JSONLoader().load_locale_data()
        init_i18n(locales)
