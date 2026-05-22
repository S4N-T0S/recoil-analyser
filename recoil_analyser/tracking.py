"""Sub-pixel tracking of a fixed world feature (the wall tag, or the box).

Each frame is matched against the *frame-0* template, never against the
previous frame, so tracking is drift-free over the whole clip. The reported
position is refined to sub-pixel accuracy with a parabolic fit on the
correlation surface around its peak.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class TrackPoint:
    frame: int
    x: float
    y: float
    confidence: float  # normalised cross-correlation peak in [-1, 1]


def _parabolic_offset(left: float, center: float, right: float) -> float:
    """Sub-sample peak offset in [-0.5, 0.5] from three samples around a max.

    Fits a parabola through (-1, left), (0, center), (1, right). Returns 0 when
    the curvature is degenerate (flat surface).
    """
    denom = left - 2.0 * center + right
    if abs(denom) < 1e-12:
        return 0.0
    off = 0.5 * (left - right) / denom
    # Guard against numerical blow-ups when the peak is not a true maximum.
    if off < -1.0 or off > 1.0:
        return 0.0
    return off


class TemplateTracker:
    """Tracks one ROI across frames via normalised-cross-correlation matching.

    Args:
        template_gray: the grayscale template cropped from frame 0.
        init_center:   (x, y) centre of that template in frame-0 coordinates.
        search_margin: half-size (px) of the window searched around the last
                       known position. ``None`` searches the whole frame
                       (robust but slower). A generous margin is faster and,
                       because the tag is the only strong feature on the wall,
                       still safe.
    """

    def __init__(
        self,
        template_gray: np.ndarray,
        init_center: tuple[float, float],
        search_margin: int | None = 220,
    ) -> None:
        if template_gray.ndim != 2:
            raise ValueError("template must be single-channel grayscale")
        self.template = template_gray
        self.th, self.tw = template_gray.shape[:2]
        self.last = (float(init_center[0]), float(init_center[1]))
        self.search_margin = search_margin

    def track(self, frame_gray: np.ndarray, frame_index: int) -> TrackPoint:
        h, w = frame_gray.shape[:2]
        if self.search_margin is None:
            search = frame_gray
            ox = oy = 0
        else:
            cx, cy = self.last
            m = self.search_margin
            ox = int(max(0, cx - self.tw / 2.0 - m))
            oy = int(max(0, cy - self.th / 2.0 - m))
            x1 = int(min(w, cx + self.tw / 2.0 + m))
            y1 = int(min(h, cy + self.th / 2.0 + m))
            search = frame_gray[oy:y1, ox:x1]

        # Window too small to hold the template (e.g. near an edge): fall back
        # to a whole-frame search so we never lose the feature.
        if search.shape[0] < self.th or search.shape[1] < self.tw:
            search = frame_gray
            ox = oy = 0

        res = cv2.matchTemplate(search, self.template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        px, py = max_loc

        dx = dy = 0.0
        if 0 < px < res.shape[1] - 1:
            dx = _parabolic_offset(res[py, px - 1], res[py, px], res[py, px + 1])
        if 0 < py < res.shape[0] - 1:
            dy = _parabolic_offset(res[py - 1, px], res[py, px], res[py + 1, px])

        cx = ox + px + dx + self.tw / 2.0
        cy = oy + py + dy + self.th / 2.0
        self.last = (cx, cy)
        return TrackPoint(frame=frame_index, x=cx, y=cy, confidence=float(max_val))
