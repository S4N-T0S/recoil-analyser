"""Serialise results to JSON and render a recoil-pattern plot."""

from __future__ import annotations

import json
from pathlib import Path

from .core import AnalysisResult


def save_json(result: AnalysisResult, path: str | Path, *, include_trajectory: bool = True) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(result.data)
    if not include_trajectory:
        data.pop("trajectory", None)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return path


def save_plot(result: AnalysisResult, path: str | Path, *, show: bool = False) -> Path | None:
    """Render the per-bullet recoil pattern (and faint full trajectory).

    Y is inverted so up on the plot is up on screen (recoil up). Returns None if
    matplotlib is unavailable.
    """
    try:
        import matplotlib

        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pattern = result.data["pattern"]
    if not pattern:
        return None

    xs = [p["x"] for p in pattern]
    ys = [p["y"] for p in pattern]

    with plt.style.context("dark_background"):
        fig, ax = plt.subplots(figsize=(7, 9))

        if result.aim_xy is not None:
            ax.plot(
                result.aim_xy[:, 0], result.aim_xy[:, 1],
                color="0.45", lw=1, zorder=1, label="view path (all frames)",
            )

        ax.plot(xs, ys, "-o", color="#ff5252", ms=4, lw=1.2, zorder=2, label="bullets")
        for p in pattern:
            ax.annotate(str(p["bullet"]), (p["x"], p["y"]),
                        textcoords="offset points", xytext=(5, 2), fontsize=7, color="0.85")
        ax.scatter([xs[0]], [ys[0]], color="#4caf50", zorder=3, s=60, label="bullet 1")

        ax.invert_yaxis()  # screen +y is down; show recoil-up as up
        ax.set_aspect("equal", adjustable="datalim")
        ax.axhline(0, color="0.4", lw=0.8)
        ax.axvline(0, color="0.4", lw=0.8)
        ax.set_xlabel("horizontal (px)   +right")
        ax.set_ylabel("vertical (px)   +down")
        rpm = result.data["rpm"]["video_span"]
        ax.set_title(
            f"{result.data['weapon']} recoil  -  "
            f"{result.data['shots_detected']} shots"
            + (f"  -  ~{rpm:.0f} RPM" if rpm else "")
        )
        ax.legend(loc="best", fontsize=8)
        ax.grid(True, color="0.22")
        fig.tight_layout()
        fig.savefig(path, dpi=130, facecolor=fig.get_facecolor())
        if show:
            plt.show()
        plt.close(fig)
    return path
