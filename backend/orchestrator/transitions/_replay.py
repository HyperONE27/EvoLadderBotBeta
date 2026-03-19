"""Replay insertion, status updates, match refs, and auto-resolution."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import polars as pl
import structlog

from backend.domain_types.dataframes import Matches1v1Row
from common.datetime_helpers import utc_now

if TYPE_CHECKING:
    from backend.orchestrator.transitions import TransitionManager

logger = structlog.get_logger(__name__)


def insert_replay_1v1_pending(
    self: TransitionManager,
    match_id: int,
    discord_uid: int,
    parsed: dict,
    initial_path: str,
    uploaded_at: datetime,
) -> dict:
    """
    Insert a replay row with ``upload_status='pending'`` and return the
    created row (which contains the DB-assigned ``id``).

    Write-through: DB is written first, then the in-memory cache is updated.
    """
    data = {
        "matches_1v1_id": match_id,
        "replay_path": initial_path,
        "replay_hash": parsed["replay_hash"],
        "replay_time": parsed["replay_time"],
        "uploaded_at": uploaded_at.isoformat(),
        "player_1_name": parsed["player_1_name"],
        "player_2_name": parsed["player_2_name"],
        "player_1_race": parsed["player_1_race"],
        "player_2_race": parsed["player_2_race"],
        "match_result": parsed["match_result"],
        "player_1_handle": parsed["player_1_handle"],
        "player_2_handle": parsed["player_2_handle"],
        "observers": parsed["observers"],
        "map_name": parsed["map_name"],
        "game_duration_seconds": parsed["game_duration_seconds"],
        "game_privacy": parsed["game_privacy"],
        "game_speed": parsed["game_speed"],
        "game_duration_setting": parsed["game_duration_setting"],
        "locked_alliances": parsed["locked_alliances"],
        "cache_handles": parsed["cache_handles"],
        "upload_status": "pending",
    }

    # DB write first (write-through).
    created = self._db_writer.add_replay_1v1(data)

    # Update in-memory cache.
    df = self._state_manager.replays_1v1_df
    self._state_manager.replays_1v1_df = df.vstack(
        pl.DataFrame([created]).cast(df.schema)
    )

    return created


def update_replay_status(
    self: TransitionManager,
    replay_id: int,
    status: str,
    final_path: str | None = None,
) -> None:
    """
    Update ``upload_status`` for a replay row.  If *final_path* is given,
    also update ``replay_path`` (used when changing from the initial
    placeholder to the Supabase public URL).

    Write-through: DB is written first, then the in-memory cache is updated.
    """
    # DB write first.
    self._db_writer.update_replay_1v1_status(replay_id, status, final_path)

    # Update in-memory cache by swapping the row.
    df = self._state_manager.replays_1v1_df
    rows = df.filter(pl.col("id") == replay_id)
    if rows.is_empty():
        return

    row = rows.row(0, named=True)
    row["upload_status"] = status
    if final_path is not None:
        row["replay_path"] = final_path

    self._state_manager.replays_1v1_df = df.filter(pl.col("id") != replay_id).vstack(
        pl.DataFrame([row]).cast(df.schema)
    )


def update_match_replay_refs(
    self: TransitionManager,
    match_id: int,
    player_num: int,
    replay_path: str,
    replay_row_id: int,
    uploaded_at: datetime,
) -> None:
    """
    Update a match row with the latest replay path, replay row ID, and
    upload timestamp for the given player number (1 or 2).

    Write-through: DB is written first, then the in-memory cache is updated.
    """
    # DB write first.
    self._db_writer.update_match_1v1_replay(
        match_id, player_num, replay_path, replay_row_id, uploaded_at
    )

    # Update in-memory cache using the generic row-swap helper.
    self._update_match_cache(
        match_id,
        **{
            f"player_{player_num}_replay_path": replay_path,
            f"player_{player_num}_replay_row_id": replay_row_id,
            f"player_{player_num}_uploaded_at": uploaded_at,
        },
    )


def replay_auto_resolve_match(
    self: TransitionManager,
    match_id: int,
    uploader_discord_uid: int,
    replay_result: str,
) -> Matches1v1Row:
    """Auto-resolve a match based on a validated replay.

    The replay has already passed race, map, and timestamp checks.
    ``replay_result`` is the result from the replay parser perspective
    (``player_1_win``, ``player_2_win``, or ``draw``) relative to the
    *replay* player order — which may differ from the match player order.
    The caller is responsible for mapping the replay winner's race to the
    correct match player before calling this method, so ``replay_result``
    here is already in match-player terms (``player_1_win`` means the
    match's player 1 won).

    The uploader's report column is set to ``replay_result``.  The
    opponent's report column is set to ``no_report`` only if it is
    currently empty.
    """
    match = self._get_match_row(match_id)
    if match is None:
        raise ValueError(f"Match #{match_id} not found for auto-resolve")

    p1_uid = match["player_1_discord_uid"]

    # Determine report columns.
    if uploader_discord_uid == p1_uid:
        p1_report: str | None = replay_result
        p2_report: str | None = (
            "no_report" if match["player_2_report"] is None else None
        )
    else:
        p2_report = replay_result
        p1_report = "no_report" if match["player_1_report"] is None else None

    now = utc_now()
    new_p1_mmr, new_p2_mmr, p1_change, p2_change = self._calculate_mmr_changes(
        match, replay_result
    )

    updated = self._apply_match_resolution(
        match_id,
        match,
        replay_result,
        p1_change,
        p2_change,
        new_p1_mmr,
        new_p2_mmr,
        now,
        player_1_report=p1_report,
        player_2_report=p2_report,
    )

    logger.info(
        f"Match #{match_id} auto-resolved via replay upload by "
        f"{uploader_discord_uid}: {replay_result} "
        f"(p1 {match['player_1_mmr']}→{new_p1_mmr}, "
        f"p2 {match['player_2_mmr']}→{new_p2_mmr})"
    )
    return updated
