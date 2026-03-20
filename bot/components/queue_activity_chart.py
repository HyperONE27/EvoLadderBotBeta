"""PNG line chart for queue join analytics (matplotlib Agg backend)."""

from __future__ import annotations

import io
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.colors import to_rgba
from matplotlib.patches import PathPatch
from matplotlib.path import Path

from common.i18n import t

_BG = "#18191c"
_LINE_COLOR = "#5B8FFF"
_GRID_COLOR = "#2e2f33"
_LABEL_COLOR = "#888888"
_TEXT_COLOR = "#e0e0e0"
_SPINE_COLOR = "#444444"
_PEAK_COLOR = "#ff4444"


def _apply_style(fig: plt.Figure, ax: plt.Axes) -> None:
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_BG)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color(_SPINE_COLOR)
    ax.yaxis.grid(True, color=_GRID_COLOR, linewidth=0.8)
    ax.xaxis.grid(False)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", length=0, pad=8, colors=_LABEL_COLOR)


def render_queue_join_chart_png(
    buckets: list[dict],
    *,
    title: str,
    locale: str = "enUS",
    y_label: str | None = None,
    game_mode: str | None = None,
) -> io.BytesIO:
    """Build a PNG line chart; *buckets* items have ``t`` (ISO) and ``count`` (int)."""

    buf = io.BytesIO()
    y_axis = y_label if y_label is not None else t("activity_chart.y_axis.1", locale)
    chart_title = f"Queue Activity · {game_mode}" if game_mode else title

    if not buckets:
        fig, ax = plt.subplots(figsize=(10, 4))
        _apply_style(fig, ax)
        empty_msg = t("activity_chart.empty.1", locale)
        ax.text(0.5, 0.5, empty_msg, ha="center", va="center", color=_TEXT_COLOR)
        ax.set_axis_off()
        fig.savefig(
            buf,
            format="png",
            bbox_inches="tight",
            dpi=150,
            facecolor=fig.get_facecolor(),
        )
        plt.close(fig)
        buf.seek(0)
        return buf

    times: list[datetime] = []
    counts: list[int] = []
    for b in buckets:
        raw_t = b["t"]
        if isinstance(raw_t, str):
            dt = datetime.fromisoformat(raw_t.replace("Z", "+00:00"))
        else:
            dt = raw_t
        times.append(dt)
        counts.append(int(b["count"]))

    fig, ax = plt.subplots(figsize=(10, 4))
    _apply_style(fig, ax)

    # date2num satisfies matplotlib stubs; plain datetime lists trip mypy on some stubs.
    x_nums = mdates.date2num(times)
    counts_arr = np.array(counts, dtype=float)

    # Gradient fill: imshow with alpha ramp, clipped to the area under the line.
    ymax_fill = float(counts_arr.max()) * 1.5
    grad = np.zeros((256, 1, 4), dtype=float)
    grad[:, 0, :3] = to_rgba(_LINE_COLOR)[:3]
    grad[:, 0, 3] = np.linspace(0.35, 0.0, 256)  # opaque at top, transparent at bottom
    im = ax.imshow(
        grad,
        aspect="auto",
        extent=(x_nums[0], x_nums[-1], 0.0, ymax_fill),
        origin="upper",
        zorder=2,
    )
    n = len(x_nums)
    clip_verts = np.empty((n + 3, 2))
    clip_verts[0] = [x_nums[0], 0.0]
    clip_verts[1 : n + 1] = np.column_stack([x_nums, counts_arr])
    clip_verts[n + 1] = [x_nums[-1], 0.0]
    clip_verts[n + 2] = [x_nums[0], 0.0]
    clip_codes = np.full(n + 3, Path.LINETO, dtype=np.uint8)
    clip_codes[0] = Path.MOVETO
    clip_codes[-1] = Path.CLOSEPOLY
    clip_patch = PathPatch(
        Path(clip_verts, clip_codes), transform=ax.transData, visible=False
    )
    ax.add_patch(clip_patch)
    im.set_clip_path(clip_patch)

    # Gradient line: LineCollection with alpha fading in left-to-right.
    points = np.column_stack([x_nums, counts_arr]).reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)
    n_seg = len(segments)
    seg_colors = np.zeros((n_seg, 4))
    seg_colors[:, :3] = to_rgba(_LINE_COLOR)[:3]
    seg_colors[:, 3] = np.linspace(0.4, 1.0, n_seg)
    lc = LineCollection(
        segments.tolist(), colors=seg_colors, linewidth=2.5, zorder=4, capstyle="round"
    )
    ax.add_collection(lc)

    # Red dot at peak.
    peak_idx = int(np.argmax(counts_arr))
    ax.scatter(
        [x_nums[peak_idx]], [counts_arr[peak_idx]], color=_PEAK_COLOR, s=70, zorder=5
    )

    ax.set_title(chart_title, fontsize=13, fontweight="600", color=_TEXT_COLOR, pad=16)
    ax.set_ylabel(y_axis, fontsize=10, color=_LABEL_COLOR, labelpad=10)
    ax.set_xlim(x_nums[0], x_nums[-1])
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))

    locator = mdates.AutoDateLocator()
    formatter = mdates.ConciseDateFormatter(locator)
    formatter.show_offset = False
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)

    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(
        buf, format="png", bbox_inches="tight", dpi=150, facecolor=fig.get_facecolor()
    )
    plt.close(fig)
    buf.seek(0)
    return buf
