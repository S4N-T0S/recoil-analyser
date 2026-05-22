"""Generate a synthetic clip with a KNOWN recoil pattern, for validation.

The 'world' layer (wall + tag + box) is translated each frame by ``-A(frame)``
where ``A`` is the injected aim trajectory; a fixed HUD ammo counter and a
muzzle flash are composited on top. Because the analyser computes
``aim = -(feature_displacement)``, it should recover ``A`` (and thus the
injected per-bullet pattern) up to sub-pixel/compression error.

Returns the ground-truth metadata so a validator can compare.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

WIDTH, HEIGHT, FPS = 1280, 720, 120.0
WALL = (235, 235, 235)

# ROIs (x, y, w, h) - the validator passes these straight to the analyser.
TAG_ROI = (80, 90, 240, 90)
BOX_ROI = (60, 380, 320, 260)
AMMO_ROI = (1070, 655, 180, 55)
MUZZLE_ROI = (560, 460, 160, 160)

# Injected per-bullet aim pattern in screen px (+x right, +y down; up = -y).
PATTERN = [
    (0.0, 0.0), (2.0, -6.0), (-3.0, -13.0), (1.5, -19.0), (5.0, -24.0),
    (-2.0, -28.0), (-6.0, -31.0), (0.0, -33.0), (4.0, -34.0), (-1.0, -35.0),
]
FIRST_SHOT = 1
SHOT_INTERVAL = 8
N_FRAMES = 90


def shot_frames() -> list[int]:
    return [FIRST_SHOT + SHOT_INTERVAL * k for k in range(len(PATTERN))]


def _aim(frame: int) -> tuple[float, float]:
    sf = shot_frames()
    if frame <= sf[0]:
        return PATTERN[0]
    if frame >= sf[-1]:
        return PATTERN[-1]
    for k in range(len(sf) - 1):
        if sf[k] <= frame <= sf[k + 1]:
            t = (frame - sf[k]) / (sf[k + 1] - sf[k])
            ax = PATTERN[k][0] + t * (PATTERN[k + 1][0] - PATTERN[k][0])
            ay = PATTERN[k][1] + t * (PATTERN[k + 1][1] - PATTERN[k][1])
            return (ax, ay)
    return PATTERN[-1]


def _base_world() -> np.ndarray:
    img = np.full((HEIGHT, WIDTH, 3), WALL, dtype=np.uint8)
    # faint noise so the wall isn't perfectly flat (like a real low-settings capture)
    noise = np.random.default_rng(0).integers(-3, 4, (HEIGHT, WIDTH, 1), dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    # Tag: high-contrast textured patch (good for correlation tracking).
    x, y, w, h = TAG_ROI
    cv2.rectangle(img, (x, y), (x + w, y + h), (20, 20, 20), -1)
    cv2.rectangle(img, (x + 8, y + 8), (x + w - 8, y + h - 8), (245, 245, 245), -1)
    cv2.rectangle(img, (x + 16, y + 16), (x + 60, y + h - 16), (10, 10, 10), -1)
    cv2.circle(img, (x + w - 40, y + h // 2), 22, (0, 0, 0), -1)
    cv2.putText(img, "T4G", (x + 75, y + h - 26), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 3)

    # Box: dark object on the left with markings.
    bx, by, bw, bh = BOX_ROI
    cv2.rectangle(img, (bx, by), (bx + bw, by + bh), (55, 55, 55), -1)
    cv2.rectangle(img, (bx, by), (bx + bw, by + bh), (15, 15, 15), 3)
    cv2.putText(img, "BICU 163248", (bx + 14, by + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 230), 2)
    cv2.putText(img, "THE FINALS", (bx + 14, by + bh - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 230), 2)
    return img


def generate(path: str | Path) -> dict:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    base = _base_world()
    sf = shot_frames()
    mag = len(PATTERN)

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError("Could not open VideoWriter (mp4v)")

    for f in range(N_FRAMES):
        ax, ay = _aim(f)
        m = np.float32([[1, 0, -ax], [0, 1, -ay]])  # world shifts opposite to aim
        frame = cv2.warpAffine(base, m, (WIDTH, HEIGHT), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=WALL)

        # Gun body (fixed overlay, dark) so the muzzle ROI has a dark baseline
        # that a flash spikes against - as in real footage.
        cv2.rectangle(frame, (470, 470), (810, HEIGHT), (45, 45, 45), -1)
        cv2.rectangle(frame, (600, 455), (700, 520), (30, 30, 30), -1)

        # HUD ammo counter (fixed): decrements on each shot frame.
        fired = sum(1 for s in sf if s <= f)
        count = mag - fired
        ax0, ay0, aw, ah = AMMO_ROI
        cv2.rectangle(frame, (ax0, ay0), (ax0 + aw, ay0 + ah), (30, 30, 30), -1)
        cv2.putText(frame, f"{count}/{mag}", (ax0 + 8, ay0 + 42),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (240, 240, 240), 2)

        # Muzzle flash on the exact shot frame.
        if f in sf:
            cx, cy = MUZZLE_ROI[0] + MUZZLE_ROI[2] // 2, MUZZLE_ROI[1] + MUZZLE_ROI[3] // 2
            cv2.circle(frame, (cx, cy), 46, (60, 240, 255), -1)
            cv2.circle(frame, (cx, cy), 22, (255, 255, 255), -1)

        writer.write(frame)
    writer.release()

    expected = [
        {"bullet": k + 1, "frame": sf[k],
         "x": PATTERN[k][0] - PATTERN[0][0], "y": PATTERN[k][1] - PATTERN[0][1]}
        for k in range(mag)
    ]
    return {
        "path": str(path),
        "magazine": mag,
        "shot_frames": sf,
        "tag_roi": TAG_ROI,
        "box_roi": BOX_ROI,
        "ammo_roi": AMMO_ROI,
        "muzzle_roi": MUZZLE_ROI,
        "expected_pattern": expected,
        "fps": FPS,
    }


if __name__ == "__main__":
    meta = generate("output/_synthetic_test.mp4")
    print("wrote", meta["path"], "shots at", meta["shot_frames"])
