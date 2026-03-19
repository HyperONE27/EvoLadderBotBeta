"""TypedDict for event rows as passed to DatabaseWriter.insert_event()."""

from typing import Any, TypedDict


class EventRow(TypedDict, total=False):
    """Partial row dict sent to DatabaseWriter.insert_event().

    Only discord_uid, event_type, action, and event_data are required.
    The remaining wide columns are optional and default to NULL in the DB.
    """

    discord_uid: int  # Required — actual UID or sentinel (1=backend, 2=bot)
    event_type: str  # Required — broad category
    action: str  # Required — specific sub-type
    game_mode: str | None  # "1v1", "2v2", "FFA" — NULL for non-match events
    match_id: int | None  # NULL for non-match events
    target_discord_uid: int | None  # NULL except for admin/owner actions on a player
    event_data: dict[str, Any]  # Required — full serialised payload
