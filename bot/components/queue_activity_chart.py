"""PNG line chart for queue join analytics (matplotlib Agg backend)."""

from __future__ import annotations

import io
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from common.i18n import t


def render_queue_join_chart_png(
    buckets: list[dict],
    *,
    title: str,
    locale: str = "enUS",
    y_label: str | None = None,
) -> io.BytesIO:
    """Build a PNG line chart; *buckets* items have ``t`` (ISO) and ``count`` (int)."""

    buf = io.BytesIO()
    y_axis = y_label if y_label is not None else t("activity_chart.y_axis.1", locale)
    if not buckets:
        fig, ax = plt.subplots(figsize=(10, 4))
        empty_msg = t("activity_chart.empty.1", locale)
        ax.text(0.5, 0.5, empty_msg, ha="center", va="center")
        ax.set_axis_off()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf

    times: list[datetime] = []
    counts: list[int] = []
    for b in buckets:
        raw_t = b["t"]
        if isinstance(raw_t, str):
            t = datetime.fromisoformat(raw_t.replace("Z", "+00:00"))
        else:
            t = raw_t
        times.append(t)
        counts.append(int(b["count"]))

    fig, ax = plt.subplots(figsize=(10, 4))
    # date2num satisfies matplotlib stubs; plain datetime lists trip mypy on some stubs.
    x_nums = mdates.date2num(times)
    ax.plot(x_nums, counts, marker=".", linewidth=1.5)
    ax.set_title(title)
    ax.set_ylabel(y_axis)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    fig.autofmt_xdate()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf
