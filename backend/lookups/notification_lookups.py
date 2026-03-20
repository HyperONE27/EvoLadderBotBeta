import polars as pl

from backend.domain_types.dataframes import NotificationsRow, row_as
from backend.orchestrator.state import StateManager

_MODULE_NOT_INITIALIZED: str = f"{__name__} not initialized"

_state_manager: StateManager | None = None

# ----------------
# Internal helpers
# ----------------


def _get_state_manager() -> StateManager:
    if _state_manager is None:
        raise RuntimeError(_MODULE_NOT_INITIALIZED)
    return _state_manager


def _get_notifications() -> pl.DataFrame:
    return _get_state_manager().notifications_df


# ----------------
# Public interface
# ----------------


def get_notification_by_discord_uid(discord_uid: int) -> NotificationsRow | None:
    """Return a single notification row, or None if not present."""
    df = _get_notifications()
    if df.is_empty():
        return None
    rows = df.filter(pl.col("discord_uid") == discord_uid)
    if rows.is_empty():
        return None
    return row_as(NotificationsRow, rows.row(0, named=True))


def get_queue_activity_subscribers(joiner_uid: int, game_mode: str) -> pl.DataFrame:
    """Return eligible subscribers for queue-activity notifications.

    Joins notifications with players to filter by opt-in, setup completion,
    ToS acceptance, ban status, and idle status.  Excludes *joiner_uid*.

    Returns a DataFrame with columns from both tables, including
    ``queue_notify_cooldown_minutes`` and ``language``.
    """
    if game_mode != "1v1":
        return pl.DataFrame()

    sm = _get_state_manager()
    ndf = sm.notifications_df
    pdf = sm.players_df
    if ndf.is_empty():
        return pl.DataFrame()

    subs = ndf.filter(pl.col("notify_queue_1v1"))
    if subs.is_empty():
        return pl.DataFrame()

    joined = subs.join(
        pdf.select(
            "discord_uid",
            "completed_setup",
            "accepted_tos",
            "is_banned",
            "player_status",
            "language",
        ),
        on="discord_uid",
        how="inner",
    )
    return joined.filter(
        (pl.col("discord_uid") != joiner_uid)
        & pl.col("completed_setup")
        & pl.col("accepted_tos")
        & ~pl.col("is_banned")
        & (pl.col("player_status") == "idle")
    )


# ----------------
# Module lifecycle
# ----------------


def init_notification_lookups(state_manager: StateManager) -> None:
    """Initialize the notification lookups module."""
    global _state_manager
    _state_manager = state_manager
