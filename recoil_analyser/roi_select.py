"""Interactive ROI picking via OpenCV's HighGUI, with display down-scaling.

A 1440p frame is larger than most screens, so we show a scaled copy for
selection and map the chosen rectangle back to full-resolution coordinates.
"""

from __future__ import annotations

import sys
import cv2
import numpy as np

ROI = tuple[int, int, int, int]


def grab_first_content_frame(
    cap: cv2.VideoCapture, max_skip: int = 60, thresh: float = 8.0
) -> tuple[np.ndarray | None, int]:
    """Read frames from ``cap`` until the first non-black one; return it + count.

    Re-encoders (e.g. HandBrake) sometimes prepend a black frame, which would
    otherwise become the ROI-picker image and the tracking template. We skip
    leading near-black frames (mean brightness <= ``thresh``) up to ``max_skip``
    so the analysis starts on the first real frame. Recoil clips are bright
    white walls, so a low threshold can't be tripped by genuine content.
    """
    skipped = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            return None, skipped
        if float(frame.mean()) > thresh or skipped >= max_skip:
            return frame, skipped
        skipped += 1


def first_frame(video_path: str) -> np.ndarray:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open video: {video_path}")
    frame, _ = grab_first_content_frame(cap)
    cap.release()
    if frame is None:
        raise RuntimeError("Video has no frames")
    return frame


def _draw_banner(img: np.ndarray, lines: list[str]) -> None:
    """Draw an instruction banner across the top of the display image."""
    pad = 10
    line_h = 26
    height = pad * 2 + line_h * len(lines)
    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (img.shape[1], height), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, img, 0.4, 0, img)
    for i, text in enumerate(lines):
        y = pad + line_h * (i + 1) - 6
        color = (0, 220, 255) if i == 0 else (235, 235, 235)
        weight = 2 if i == 0 else 1
        cv2.putText(img, text, (pad, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, weight, cv2.LINE_AA)


def _select_rect(win: str, img: np.ndarray) -> ROI | None:
    """Drag a box on ``img``; confirm with ENTER/SPACE. Returns (x, y, w, h).

    Returns None if the user cancels - by pressing ESC *or* by closing the
    window with its X button.
    """
    color = (255, 0, 0)
    state = {"p0": None, "p1": None, "dragging": False}

    def on_mouse(event: int, x: int, y: int, _flags: int, _param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            state["p0"] = (x, y)
            state["p1"] = (x, y)
            state["dragging"] = True
        elif event == cv2.EVENT_MOUSEMOVE and state["dragging"]:
            state["p1"] = (x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            state["p1"] = (x, y)
            state["dragging"] = False

    try:
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    except cv2.error as e:
        if "The function is not implemented" in str(e):
            sys.exit(
                "\nError: OpenCV GUI functions are not available.\n"
                "This usually means 'opencv-python-headless' is installed instead of 'opencv-python'.\n"
                "The interactive picker requires the standard 'opencv-python' package to display windows."
            )
        raise

    cv2.setMouseCallback(win, on_mouse)
    try:
        while True:
            shown = img
            if state["p0"] is not None and state["p1"] is not None:
                shown = img.copy()
                (x0, y0), (x1, y1) = state["p0"], state["p1"]
                left, right = min(x0, x1), max(x0, x1)
                top, bottom = min(y0, y1), max(y0, y1)
                cx, cy = (left + right) // 2, (top + bottom) // 2
                cv2.rectangle(shown, (left, top), (right, bottom), color, 2, 1)
                cv2.line(shown, (left, cy), (right, cy), color, 1, cv2.LINE_AA)
                cv2.line(shown, (cx, top), (cx, bottom), color, 1, cv2.LINE_AA)
            cv2.imshow(win, shown)
            key = cv2.waitKey(20) & 0xFF

            # X button (or any external close) -> treat as cancel.
            if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                return None
            if key == 27:  # ESC -> cancel
                return None
            if key in (13, 32):  # ENTER / SPACE -> confirm
                if state["p0"] is None or state["p1"] is None:
                    return None
                x0, y0 = state["p0"]
                x1, y1 = state["p1"]
                return (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
    finally:
        try:
            cv2.destroyWindow(win)
            cv2.waitKey(1)  # let the window actually close on Windows
        except cv2.error:
            pass


def select_roi_scaled(
    frame: np.ndarray,
    title: str,
    max_dim: int = 1500,
    instructions: list[str] | None = None,
) -> ROI | None:
    """Show ``frame`` (scaled to fit) and return the drawn ROI in full-res px.

    ``instructions`` are drawn as a banner on the image itself so the guidance
    is visible in the popup, not just the main window. Returns None if the user
    cancels (ESC, or closing the window) or draws an empty box.
    """
    h, w = frame.shape[:2]
    scale = min(1.0, max_dim / max(h, w))
    disp = cv2.resize(frame, (round(w * scale), round(h * scale))) if scale < 1.0 else frame.copy()

    if instructions:
        _draw_banner(disp, instructions)

    rect = _select_rect(title, disp)
    if rect is None:
        return None

    x, y, rw, rh = rect
    if rw == 0 or rh == 0:
        return None
    inv = 1.0 / scale
    return (round(x * inv), round(y * inv), round(rw * inv), round(rh * inv))
