"""HTTP helper for queue-join analytics (used by /activity and chart views)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from bot.core.config import BACKEND_URL
from bot.core.http import get_session
from common.datetime_helpers import to_iso
from common.i18n import t


def activity_chart_title(locale: str, game_mode: str, range_key: str) -> str:
    """Chart title for *range_key* ``24h`` / ``7d`` / ``30d``."""

    range_label = t(f"activity_embed.range.{range_key}", locale)
    return t(
        "activity_embed.title.1",
        locale,
        game_mode=game_mode,
        range_label=range_label,
    )


async def fetch_queue_join_analytics(
    game_mode: str,
    start: datetime,
    end: datetime,
    *,
    dedupe: bool = False,
) -> dict[str, Any]:
    params = {
        "start": to_iso(dt=start) or "",
        "end": to_iso(dt=end) or "",
        "game_mode": game_mode,
        "dedupe": str(dedupe).lower(),
    }
    url = f"{BACKEND_URL}/analytics/queue_joins"
    async with get_session().get(url, params=params) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"analytics {resp.status}: {text}")
        return cast(dict[str, Any], await resp.json())
