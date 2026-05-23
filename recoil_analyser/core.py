"""End-to-end recoil analysis: video in, structured recoil result out.

The video is processed in a single pass. Per frame we (a) track the wall tag to
sub-pixel accuracy and (b) accumulate the small 1-D signals used for shot
detection. Full frames are never retained, so memory stays low even for 1440p.

Coordinate convention (matches the on-screen view):
    x -> right is positive,  y -> down is positive.
Recoil pushes the *view* up/right, which is the same as the aim point on the
wall moving up/right, so a typical upward kick yields **negative y**. The aim
displacement equals the negative of the tracked tag displacement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

from .audio import estimate_rpm_from_audio
from .detection import estimate_rpm, find_shot_frames, launch_sample_frames
from .geometry import CameraGeometry
from .roi_select import grab_first_content_frame
from .tracking import TemplateTracker, TrackPoint

ROI = tuple[int, int, int, int]  # x, y, w, h


@dataclass
class AnalysisConfig:
    video_path: str
    tag_roi: ROI
    weapon: str = "Unknown"
    magazine: int | None = None
    shot_method: str = "ammo"  # "ammo" | "muzzle"
    ammo_roi: ROI | None = None
    muzzle_roi: ROI | None = None
    box_roi: ROI | None = None
    fov_deg: float = 81.0
    fov_axis: str = "vertical"
    distance_m: float = 13.0
    search_margin: int | None = 220
    use_audio: bool = True
    progress: Callable[[int, int], None] | None = None


@dataclass
class AnalysisResult:
    data: dict  # JSON-ready
    # Raw arrays kept for plotting / debugging (not serialised by default):
    tag_track: list[TrackPoint] = field(default_factory=list)
    box_track: list[TrackPoint] = field(default_factory=list)
    aim_xy: np.ndarray | None = None  # (n_frames, 2), origin = first shot
    shot_frames: list[int] = field(default_factory=list)


def _crop(frame: np.ndarray, roi: ROI) -> np.ndarray:
    x, y, w, h = roi
    return frame[y : y + h, x : x + w]


def _roi_center(roi: ROI) -> tuple[float, float]:
    x, y, w, h = roi
    return (x + w / 2.0, y + h / 2.0)


def analyse(cfg: AnalysisConfig) -> AnalysisResult:
    cap = cv2.VideoCapture(cfg.video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open video: {cfg.video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 120.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n_frames_hint = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    if cfg.shot_method == "ammo" and cfg.ammo_roi is None:
        raise ValueError("shot_method='ammo' requires ammo_roi")
    if cfg.shot_method == "muzzle" and cfg.muzzle_roi is None:
        raise ValueError("shot_method='muzzle' requires muzzle_roi")

    geom = CameraGeometry(width, height, cfg.fov_deg, cfg.fov_axis, cfg.distance_m)

    # ---- read frame 0, build templates ----------------------------------
    # Skip any leading black frames (re-encoders like HandBrake can prepend one)
    # so the template and origin land on the first real frame.
    frame0, skipped_leading = grab_first_content_frame(cap)
    if frame0 is None:
        cap.release()
        raise RuntimeError("Video has no frames")
    gray0 = cv2.cvtColor(frame0, cv2.COLOR_BGR2GRAY)

    tag_template = _crop(gray0, cfg.tag_roi).copy()
    tag_tracker = TemplateTracker(tag_template, _roi_center(cfg.tag_roi), cfg.search_margin)

    box_tracker = None
    if cfg.box_roi is not None:
        box_template = _crop(gray0, cfg.box_roi).copy()
        box_tracker = TemplateTracker(box_template, _roi_center(cfg.box_roi), cfg.search_margin)

    prev_ammo = _crop(gray0, cfg.ammo_roi).astype(np.float32) if cfg.ammo_roi else None

    tag_pts: list[TrackPoint] = []
    box_pts: list[TrackPoint] = []
    ammo_diff: list[float] = []
    muzzle_bright: list[float] = []

    idx = 0
    gray = gray0
    while True:
        tag_pts.append(tag_tracker.track(gray, idx))
        if box_tracker is not None:
            box_pts.append(box_tracker.track(gray, idx))

        if cfg.ammo_roi is not None:
            cur = _crop(gray, cfg.ammo_roi).astype(np.float32)
            ammo_diff.append(float(np.mean(np.abs(cur - prev_ammo))) if prev_ammo is not None else 0.0)
            prev_ammo = cur
        if cfg.muzzle_roi is not None:
            muzzle_bright.append(float(np.mean(_crop(gray, cfg.muzzle_roi))))

        if cfg.progress is not None:
            cfg.progress(idx + 1, n_frames_hint)

        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        idx += 1

    cap.release()
    n_frames = len(tag_pts)

    # ---- shot detection --------------------------------------------------
    if cfg.shot_method == "ammo":
        signal = np.asarray(ammo_diff)
    else:
        signal = np.asarray(muzzle_bright)
    shot_frames = find_shot_frames(signal, n_expected=cfg.magazine, min_gap=3)
    rpm = estimate_rpm(shot_frames, fps)

    audio_rpm = None
    if cfg.use_audio:
        ar = estimate_rpm_from_audio(cfg.video_path, n_expected=cfg.magazine or len(shot_frames) or 1)
        audio_rpm = ar.rpm if ar else None

    # ---- trajectory (aim point) -----------------------------------------
    tag_xy = np.array([[p.x, p.y] for p in tag_pts])
    conf = np.array([p.confidence for p in tag_pts])
    aim_raw = -(tag_xy - tag_xy[0])  # aim = negative of feature displacement
    # Sample each bullet at the trigger-pull aim (settled frame before its kick),
    # not the ammo-counter frame; matters for violent-kick weapons (revolvers).
    sample_frames = launch_sample_frames(aim_raw, shot_frames)
    t0 = shot_frames[0] if shot_frames else 0  # time origin = first actual shot
    pos0 = sample_frames[0] if shot_frames else 0  # spatial origin = first launch
    origin = aim_raw[pos0]
    aim = aim_raw - origin

    # ---- per-bullet pattern ---------------------------------------------
    pattern = []
    for k, (f, sf) in enumerate(zip(shot_frames, sample_frames), start=1):
        px, py = float(aim[sf, 0]), float(aim[sf, 1])
        dx_deg, dy_deg = geom.px_to_deg(px, py)
        dx_cm, dy_cm = geom.px_to_cm(px, py)
        pattern.append(
            {
                "bullet": k,
                "frame": int(f),
                "sample_frame": int(sf),
                "time_s": round((f - t0) / fps, 5),
                "x": round(px, 3),
                "y": round(py, 3),
                "dx_deg": round(dx_deg, 4),
                "dy_deg": round(dy_deg, 4),
                "dx_cm": round(dx_cm, 4),
                "dy_cm": round(dy_cm, 4),
                "confidence": round(float(conf[sf]), 4),
            }
        )

    trajectory = [
        {
            "frame": i,
            "time_s": round((i - t0) / fps, 5),
            "x": round(float(aim[i, 0]), 3),
            "y": round(float(aim[i, 1]), 3),
            "confidence": round(float(conf[i]), 4),
        }
        for i in range(n_frames)
    ]

    # ---- recoil classification ------------------------------------------
    # The pre-kick sampler only moves the sample frames for a violent-kick weapon
    # that fully recovers between shots (revolver-class). For these the pattern is
    # effectively zero and ``spread_px`` is the residual measurement floor (a few
    # px from firing before the view finishes recovering), NOT real recoil.
    recovers = sample_frames != list(shot_frames)
    if pattern:
        xs = [p["x"] for p in pattern]
        ys = [p["y"] for p in pattern]
        spread_px = {
            "x": round(max(xs) - min(xs), 3),
            "y": round(max(ys) - min(ys), 3),
            "max": round(max(max(xs) - min(xs), max(ys) - min(ys)), 3),
        }
    else:
        spread_px = {"x": 0.0, "y": 0.0, "max": 0.0}

    # ---- box cross-check -------------------------------------------------
    box_check = None
    if box_pts and shot_frames:
        box_xy = np.array([[p.x, p.y] for p in box_pts])
        box_aim = -(box_xy - box_xy[0])
        box_aim -= box_aim[pos0]
        diffs = np.linalg.norm(aim[sample_frames] - box_aim[sample_frames], axis=1)
        box_check = {
            "feature": "box",
            "mean_abs_diff_px": round(float(np.mean(diffs)), 3),
            "max_abs_diff_px": round(float(np.max(diffs)), 3),
            "note": "Agreement between tag- and box-derived recoil. Large values"
            " suggest camera translation/parallax or a tracking failure.",
        }

    data = {
        "schema_version": 1,
        "weapon": cfg.weapon,
        "source_video": cfg.video_path,
        "capture": {
            "fps": round(fps, 4),
            "width": width,
            "height": height,
            "n_frames": n_frames,
            "skipped_leading_frames": skipped_leading,
            "fov_deg": cfg.fov_deg,
            "fov_axis": cfg.fov_axis,
            "distance_m": cfg.distance_m,
            "focal_px": round(geom.focal_px, 3),
        },
        "magazine": cfg.magazine,
        "shots_detected": len(shot_frames),
        "shot_method": cfg.shot_method,
        "recoil_class": "recovers_between_shots" if recovers else "standard",
        "pattern_spread_px": spread_px,
        "rpm": {
            "video_span": round(rpm.rpm, 1) if rpm.rpm is not None else None,
            "video_median": round(rpm.rpm_median, 1) if rpm.rpm_median is not None else None,
            "mechanical_max": round(rpm.rpm_max, 1) if rpm.rpm_max is not None else None,
            "mechanical_interval_frames": rpm.mechanical_interval_frames,
            "n_intervals_used": rpm.n_intervals_used,
            "audio": round(audio_rpm, 1) if audio_rpm is not None else None,
            "mean_interval_frames": round(rpm.mean_interval_frames, 2)
            if rpm.mean_interval_frames is not None
            else None,
            "std_interval_frames": round(rpm.std_interval_frames, 2)
            if rpm.std_interval_frames is not None
            else None,
            "intervals_frames": rpm.intervals_frames,
        },
        "tracking": {
            "feature": "tag",
            "method": "subpixel_template_match_ncc",
            "min_confidence": round(float(conf.min()), 4),
            "mean_confidence": round(float(conf.mean()), 4),
            "box_crosscheck": box_check,
        },
        "coordinate_convention": (
            "Screen pixels: +x right, +y down. Recoil up/right => aim moves "
            "up/right => negative y / positive x. Pattern is relative to bullet 1. "
            "time_s is relative to the first shot (bullet 1 = 0.0; pre-shot frames "
            "are negative). 'frame' remains the absolute index into the video file."
        ),
        "rois": {
            "tag": list(cfg.tag_roi),
            "ammo": list(cfg.ammo_roi) if cfg.ammo_roi else None,
            "muzzle": list(cfg.muzzle_roi) if cfg.muzzle_roi else None,
            "box": list(cfg.box_roi) if cfg.box_roi else None,
        },
        "pattern": pattern,
        "trajectory": trajectory,
    }

    return AnalysisResult(
        data=data,
        tag_track=tag_pts,
        box_track=box_pts,
        aim_xy=aim,
        shot_frames=shot_frames,
    )
