from datetime import timedelta
from typing import Any

from backend.algorithms.game_stats import count_game_stats_in_completed_window
from backend.domain_types.dataframes import (
    AdminsRow,
    Matches1v1Row,
    Matches2v2Row,
    MMRs1v1Row,
    NotificationsRow,
    PlayersRow,
    Preferences1v1Row,
    Preferences2v2Row,
)
from backend.domain_types.ephemeral import (
    LeaderboardEntry1v1,
    LeaderboardEntry2v2,
    PartyEntry2v2,
    QueueEntry1v1,
    QueueEntry2v2,
)
from backend.lookups.admin_lookups import get_admin_by_discord_uid
from backend.lookups.match_1v1_lookups import get_match_1v1_by_id
from backend.lookups.mmr_1v1_lookups import (
    get_mmr_1v1_by_discord_uid_and_race,
    get_mmrs_1v1_by_discord_uid,
)
from backend.lookups.notification_lookups import get_notification_by_discord_uid
from backend.lookups.player_lookups import (
    get_player_by_discord_uid,
    get_player_by_string,
    is_player_name_taken,
)
from backend.lookups.preferences_1v1_lookups import get_preferences_1v1_by_discord_uid
from backend.lookups.preferences_2v2_lookups import get_preferences_2v2_by_discord_uid
from backend.orchestrator.state import StateManager
from common.datetime_helpers import utc_now


class StateReader:
    def __init__(self, state_manager: StateManager) -> None:
        self._state_manager = state_manager

    # ------------------------------------------------------------------
    # Admins
    # ------------------------------------------------------------------

    def get_admin(self, discord_uid: int) -> AdminsRow | None:
        """Get an admin by their Discord UID."""
        return get_admin_by_discord_uid(discord_uid)

    # ------------------------------------------------------------------
    # Players
    # ------------------------------------------------------------------

    def get_player(self, discord_uid: int) -> PlayersRow | None:
        """Get a player by their Discord UID."""
        return get_player_by_discord_uid(discord_uid)

    def get_player_by_string(self, s: str) -> PlayersRow | None:
        """Resolve an arbitrary string to a player row (UID, player_name, or discord_username)."""
        return get_player_by_string(s)

    def is_player_name_available(
        self, player_name: str, exclude_discord_uid: int | None = None
    ) -> bool:
        """True if no other player row uses this exact player_name."""
        return not is_player_name_taken(player_name, exclude_discord_uid)

    # ------------------------------------------------------------------
    # MMR
    # ------------------------------------------------------------------

    def get_all_mmrs_1v1(self, discord_uid: int) -> list[MMRs1v1Row]:
        """Get all 1v1 MMR rows for a player."""
        return get_mmrs_1v1_by_discord_uid(discord_uid) or []

    def get_mmr_1v1(self, discord_uid: int, race: str) -> MMRs1v1Row | None:
        """Get a 1v1 MMR for a player by their Discord UID and race."""
        return get_mmr_1v1_by_discord_uid_and_race(discord_uid, race)

    # ------------------------------------------------------------------
    # Matches
    # ------------------------------------------------------------------

    def get_match_1v1(self, match_id: int) -> Matches1v1Row | None:
        """Get a 1v1 match by its ID."""
        return get_match_1v1_by_id(match_id)

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

    def get_queue_1v1(self) -> list[QueueEntry1v1]:
        """Return the current 1v1 queue (shallow copy)."""
        return list(self._state_manager.queue_1v1)

    def get_queue_2v2(self) -> list[QueueEntry2v2]:
        """Return the current 2v2 queue (shallow copy)."""
        return list(self._state_manager.queue_2v2)

    def get_parties_2v2(self) -> list[PartyEntry2v2]:
        """Return all active 2v2 parties."""
        return list(self._state_manager.parties_2v2.values())

    def get_parties_snapshot(self) -> list[dict]:
        """Return parties enriched with nationality for the admin snapshot."""
        result = []
        for p in self._state_manager.parties_2v2.values():
            leader = self.get_player(p["leader_discord_uid"])
            member = self.get_player(p["member_discord_uid"])
            result.append(
                {
                    **p,
                    "leader_nationality": (
                        leader.get("nationality") if leader is not None else None
                    )
                    or "--",
                    "member_nationality": (
                        member.get("nationality") if member is not None else None
                    )
                    or "--",
                }
            )
        return result

    def get_queue_entry_1v1(self, discord_uid: int) -> QueueEntry1v1 | None:
        """Find a specific player's queue entry, or None."""
        for entry in self._state_manager.queue_1v1:
            if entry["discord_uid"] == discord_uid:
                return entry
        return None

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    def get_preferences_1v1(self, discord_uid: int) -> Preferences1v1Row | None:
        """Get a player's 1v1 queue preferences."""
        return get_preferences_1v1_by_discord_uid(discord_uid)

    def get_preferences_2v2(self, discord_uid: int) -> Preferences2v2Row | None:
        """Get a player's 2v2 queue preferences."""
        return get_preferences_2v2_by_discord_uid(discord_uid)

    # ------------------------------------------------------------------
    # Leaderboard
    # ------------------------------------------------------------------

    def get_leaderboard_1v1(self) -> list[LeaderboardEntry1v1]:
        """Return the current 1v1 leaderboard."""
        return self._state_manager.leaderboard_1v1

    def get_leaderboard_2v2(self) -> list[LeaderboardEntry2v2]:
        """Return the current 2v2 leaderboard."""
        return self._state_manager.leaderboard_2v2

    def get_letter_rank_1v1(self, discord_uid: int | None, race: str | None) -> str:
        """Letter rank from the in-memory leaderboard, or ``\"U\"`` if unknown."""
        if discord_uid is None or not race:
            return "U"
        leaderboard = self._state_manager.leaderboard_1v1
        lookup: dict[tuple[int, str], str] = {
            (e["discord_uid"], e["race"]): e["letter_rank"] for e in leaderboard
        }
        return lookup.get((discord_uid, race), "U")

    def enrich_match_with_ranks(self, match_dict: dict) -> dict:
        """Return a copy of match_dict with player letter ranks from the leaderboard."""
        enriched = dict(match_dict)
        p1_uid: int | None = match_dict.get("player_1_discord_uid")
        p1_race: str | None = match_dict.get("player_1_race")
        p2_uid: int | None = match_dict.get("player_2_discord_uid")
        p2_race: str | None = match_dict.get("player_2_race")
        enriched["player_1_letter_rank"] = self.get_letter_rank_1v1(p1_uid, p1_race)
        enriched["player_2_letter_rank"] = self.get_letter_rank_1v1(p2_uid, p2_race)
        return enriched

    def get_letter_rank_2v2(self, uid_a: int | None, uid_b: int | None) -> str:
        """Team letter rank from the 2v2 leaderboard, or ``"U"`` if unknown."""
        if uid_a is None or uid_b is None:
            return "U"
        uid_lo, uid_hi = min(uid_a, uid_b), max(uid_a, uid_b)
        for entry in self._state_manager.leaderboard_2v2:
            if (
                entry["player_1_discord_uid"] == uid_lo
                and entry["player_2_discord_uid"] == uid_hi
            ):
                return entry["letter_rank"]
        return "U"

    def enrich_match_2v2_with_ranks(self, match_dict: dict) -> dict:
        """Return a copy of match_dict with team letter ranks from the 2v2 leaderboard."""
        enriched = dict(match_dict)
        enriched["team_1_letter_rank"] = self.get_letter_rank_2v2(
            match_dict.get("team_1_player_1_discord_uid"),
            match_dict.get("team_1_player_2_discord_uid"),
        )
        enriched["team_2_letter_rank"] = self.get_letter_rank_2v2(
            match_dict.get("team_2_player_1_discord_uid"),
            match_dict.get("team_2_player_2_discord_uid"),
        )
        return enriched

    def enrich_match_for_snapshot(self, match: Matches1v1Row | dict[str, Any]) -> dict:
        """Match row plus letter ranks and player ISO nationality codes for /snapshot."""
        m: dict[str, Any] = dict(match)
        enriched = self.enrich_match_with_ranks(m)
        p1_uid: int | None = enriched.get("player_1_discord_uid")
        p2_uid: int | None = enriched.get("player_2_discord_uid")
        p1 = self.get_player(p1_uid) if p1_uid is not None else None
        p2 = self.get_player(p2_uid) if p2_uid is not None else None
        n1 = p1.get("nationality") if p1 is not None else None
        n2 = p2.get("nationality") if p2 is not None else None
        enriched["player_1_nationality"] = n1 if n1 else "--"
        enriched["player_2_nationality"] = n2 if n2 else "--"
        return enriched

    def enrich_match_for_snapshot_2v2(
        self, match: Matches2v2Row | dict[str, Any]
    ) -> dict:
        """2v2 match row plus team letter ranks and all four player nationalities."""
        enriched = self.enrich_match_2v2_with_ranks(dict(match))

        def _nat(uid: int | None) -> str:
            if uid is None:
                return "--"
            p = self.get_player(uid)
            n = p.get("nationality") if p is not None else None
            return n if n else "--"

        enriched["team_1_player_1_nationality"] = _nat(
            enriched.get("team_1_player_1_discord_uid")
        )
        enriched["team_1_player_2_nationality"] = _nat(
            enriched.get("team_1_player_2_discord_uid")
        )
        enriched["team_2_player_1_nationality"] = _nat(
            enriched.get("team_2_player_1_discord_uid")
        )
        enriched["team_2_player_2_nationality"] = _nat(
            enriched.get("team_2_player_2_discord_uid")
        )
        return enriched

    def get_recent_period_stats_1v1(
        self, discord_uid: int, race: str
    ) -> dict[str, dict[str, int]]:
        """Per-window game counts from ``matches_1v1`` (14d / 30d / 90d by completed_at)."""

        df = self._state_manager.matches_1v1_df
        now = utc_now()
        out: dict[str, dict[str, int]] = {}
        for key, days in (("14d", 14), ("30d", 30), ("90d", 90)):
            since = now - timedelta(days=days)
            out[key] = count_game_stats_in_completed_window(
                df, discord_uid, race, since, now
            )
        return out

    def build_profile_mmrs_1v1(self, discord_uid: int) -> list[dict[str, Any]]:
        """All MMR rows for profile plus ``letter_rank`` and ``recent`` period stats."""

        mmrs = self.get_all_mmrs_1v1(discord_uid)
        result: list[dict[str, Any]] = []
        for row in mmrs:
            race = row["race"]
            d = dict(row)
            d["letter_rank"] = self.get_letter_rank_1v1(discord_uid, race)
            d["recent"] = self.get_recent_period_stats_1v1(discord_uid, race)
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------

    def get_player_location(self, discord_uid: int) -> str | None:
        """Return the geographic-region code for a player, or None."""
        player = get_player_by_discord_uid(discord_uid)
        if player is None:
            return None
        return player.get("location")

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def get_notifications_row(self, discord_uid: int) -> NotificationsRow | None:
        """Return cached notifications row if present (does not create a row)."""
        return get_notification_by_discord_uid(discord_uid)
