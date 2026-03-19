"""Admin and owner operations: ban, status reset, resolve, set MMR, toggle admin, snapshots."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import structlog

from common.datetime_helpers import utc_now
from backend.domain_types.dataframes import Matches1v1Row, row_as
from backend.domain_types.ephemeral import QueueEntry1v1

if TYPE_CHECKING:
    from backend.orchestrator.transitions import TransitionManager

logger = structlog.get_logger(__name__)


# ==================================================================
# Admin: status reset
# ==================================================================


def reset_player_status(
    self: TransitionManager, discord_uid: int
) -> tuple[bool, str | None, str | None]:
    """Reset a player's status to idle, clearing match mode and match ID.

    Returns ``(success, error_message, old_status)``.
    """
    df = self._state_manager.players_df
    rows = df.filter(pl.col("discord_uid") == discord_uid)
    if rows.is_empty():
        return False, "Player not found.", None

    row = rows.row(0, named=True)
    old_status: str = row.get("player_status") or "unknown"

    if old_status == "idle" and row.get("current_match_id") is None:
        return False, "Player is already idle with no active match.", old_status

    self._set_player_status(discord_uid, "idle", match_mode=None, match_id=None)

    logger.info(f"Admin reset player {discord_uid} status from {old_status!r} to idle")
    return True, None, old_status


# ==================================================================
# Admin: ban toggle
# ==================================================================


def toggle_ban(self: TransitionManager, discord_uid: int) -> tuple[bool, bool]:
    """Toggle is_banned for a player. Returns (success, new_is_banned)."""
    df = self._state_manager.players_df
    rows = df.filter(pl.col("discord_uid") == discord_uid)
    if rows.is_empty():
        return False, False

    player = rows.row(0, named=True)
    player_id: int = player["id"]
    old_banned: bool = player["is_banned"]
    new_banned = not old_banned

    self._db_writer.update_player_ban_status(player_id, new_banned)

    self._state_manager.players_df = df.with_columns(
        is_banned=pl.when(pl.col("discord_uid") == discord_uid)
        .then(pl.lit(new_banned))
        .otherwise(pl.col("is_banned"))
    )

    self._db_writer.insert_event(
        {
            "discord_uid": discord_uid,
            "event_type": "player_update",
            "action": "ban_toggle",
            "event_data": {
                "field_changes": {
                    "is_banned": {"before": old_banned, "after": new_banned}
                },
            },
        }
    )

    logger.info(f"Player {discord_uid} ban toggled to {new_banned}")
    return True, new_banned


# ==================================================================
# Admin: resolve match
# ==================================================================


def admin_resolve_match(
    self: TransitionManager,
    match_id: int,
    result: str,
    admin_discord_uid: int,
) -> dict:
    """Admin-resolve a match. Bypasses the two-report flow.

    Sets match_result, calculates MMR from snapshotted initial MMRs,
    sets admin_intervened=True, and returns both players to idle.

    Does NOT modify player_1_report or player_2_report.

    Args:
        match_id: Match to resolve.
        result: One of 'player_1_win', 'player_2_win', 'draw', 'invalidated'.
        admin_discord_uid: UID of the resolving admin.

    Returns:
        Dict with resolution details (match data, MMR changes, player info).
    """
    match = self._get_match_row(match_id)
    if match is None:
        return {"success": False, "error": "Match not found."}

    p1_uid = match["player_1_discord_uid"]
    p2_uid = match["player_2_discord_uid"]
    p1_mmr = match["player_1_mmr"]
    p2_mmr = match["player_2_mmr"]
    p1_race = match["player_1_race"]
    p2_race = match["player_2_race"]

    now = utc_now()

    if result == "invalidated":
        # No MMR changes — reset to snapshotted values.
        new_p1_mmr, new_p2_mmr, p1_change, p2_change = p1_mmr, p2_mmr, 0, 0
    else:
        new_p1_mmr, new_p2_mmr, p1_change, p2_change = self._calculate_mmr_changes(
            match, result
        )

    self._apply_match_resolution(
        match_id,
        match,
        result,
        p1_change,
        p2_change,
        new_p1_mmr,
        new_p2_mmr,
        now,
        admin_intervened=True,
        admin_discord_uid=admin_discord_uid,
    )

    self._db_writer.insert_event(
        {
            "discord_uid": admin_discord_uid,
            "event_type": "match_event",
            "action": "match_resolved",
            "game_mode": "1v1",
            "match_id": match_id,
            "event_data": {
                "game_mode": "1v1",
                "match_id": match_id,
                "result": result,
                "p1_uid": p1_uid,
                "p2_uid": p2_uid,
                "p1_mmr_change": p1_change,
                "p2_mmr_change": p2_change,
            },
        }
    )

    logger.info(
        f"Match #{match_id} admin-resolved by {admin_discord_uid}: "
        f"{result} (p1 {p1_mmr}→{new_p1_mmr}, p2 {p2_mmr}→{new_p2_mmr})"
    )

    return {
        "success": True,
        "match_id": match_id,
        "result": result,
        "player_1_discord_uid": p1_uid,
        "player_2_discord_uid": p2_uid,
        "player_1_name": match["player_1_name"],
        "player_2_name": match["player_2_name"],
        "player_1_race": p1_race,
        "player_2_race": p2_race,
        "player_1_nationality": self._get_player_nationality(p1_uid),
        "player_2_nationality": self._get_player_nationality(p2_uid),
        "player_1_letter_rank": self._get_player_letter_rank(p1_uid, p1_race),
        "player_2_letter_rank": self._get_player_letter_rank(p2_uid, p2_race),
        "player_1_mmr": p1_mmr,
        "player_2_mmr": p2_mmr,
        "player_1_mmr_new": new_p1_mmr,
        "player_2_mmr_new": new_p2_mmr,
        "player_1_mmr_change": p1_change,
        "player_2_mmr_change": p2_change,
        "map_name": match["map_name"],
        "server_name": match["server_name"],
    }


# ==================================================================
# Admin: set MMR (idempotent)
# ==================================================================


def admin_set_mmr(
    self: TransitionManager, discord_uid: int, race: str, new_mmr: int
) -> tuple[bool, int | None]:
    """Idempotent SET of a player's MMR. Returns (success, old_mmr)."""
    df = self._state_manager.mmrs_1v1_df
    rows = df.filter((pl.col("discord_uid") == discord_uid) & (pl.col("race") == race))
    if rows.is_empty():
        return False, None

    old_mmr: int = rows.row(0, named=True)["mmr"]

    # DB write.
    self._db_writer.set_mmr_1v1_value(discord_uid, race, new_mmr)

    # Cache update.
    self._state_manager.mmrs_1v1_df = df.with_columns(
        mmr=pl.when((pl.col("discord_uid") == discord_uid) & (pl.col("race") == race))
        .then(pl.lit(new_mmr, dtype=pl.Int16))
        .otherwise(pl.col("mmr"))
    )

    self.rebuild_leaderboard()

    logger.info(f"Admin set MMR for {discord_uid}/{race}: {old_mmr} → {new_mmr}")
    return True, old_mmr


# ==================================================================
# Owner: toggle admin role
# ==================================================================


def toggle_admin_role(
    self: TransitionManager, discord_uid: int, discord_username: str
) -> dict:
    """Toggle a user between admin and inactive. Returns result dict.

    - New user → insert with role='admin'.
    - Existing 'inactive' → set role='admin', update last_promoted_at.
    - Existing 'admin' → set role='inactive', update last_demoted_at.
    - Existing 'owner' → refuse.
    """
    df = self._state_manager.admins_df
    rows = df.filter(pl.col("discord_uid") == discord_uid)
    now = utc_now()

    if rows.is_empty():
        # New admin — insert.
        created = self._db_writer.upsert_admin(
            discord_uid=discord_uid,
            discord_username=discord_username,
            role="admin",
            first_promoted_at=now,
            last_promoted_at=now,
        )
        self._state_manager.admins_df = df.vstack(
            pl.DataFrame([created]).cast(df.schema)
        )
        logger.info(f"New admin added: {discord_username} ({discord_uid})")
        return {"success": True, "action": "promoted", "new_role": "admin"}

    current = rows.row(0, named=True)
    current_role: str = current["role"]

    if current_role == "owner":
        return {"success": False, "error": "Cannot modify owner status."}

    if current_role == "admin":
        # Demote to inactive.
        self._db_writer.update_admin_role(discord_uid, "inactive", last_demoted_at=now)
        updated = {**current, "role": "inactive", "last_demoted_at": now}
        self._state_manager.admins_df = df.filter(
            pl.col("discord_uid") != discord_uid
        ).vstack(pl.DataFrame([updated]).cast(df.schema))
        logger.info(f"Admin demoted: {discord_username} ({discord_uid})")
        return {"success": True, "action": "demoted", "new_role": "inactive"}

    # inactive → promote back.
    self._db_writer.update_admin_role(discord_uid, "admin", last_promoted_at=now)
    updated = {**current, "role": "admin", "last_promoted_at": now}
    self._state_manager.admins_df = df.filter(
        pl.col("discord_uid") != discord_uid
    ).vstack(pl.DataFrame([updated]).cast(df.schema))
    logger.info(f"Admin re-promoted: {discord_username} ({discord_uid})")
    return {"success": True, "action": "promoted", "new_role": "admin"}


# ==================================================================
# Admin: snapshot helpers
# ==================================================================


def get_queue_snapshot_1v1(self: TransitionManager) -> list[QueueEntry1v1]:
    """Return the current 1v1 queue (shallow copy)."""
    return list(self._state_manager.queue_1v1)


def get_active_matches_1v1(self: TransitionManager) -> list[Matches1v1Row]:
    """Return all matches with match_result IS NULL."""
    df = self._state_manager.matches_1v1_df
    active = df.filter(pl.col("match_result").is_null())
    return [row_as(Matches1v1Row, row) for row in active.iter_rows(named=True)]
