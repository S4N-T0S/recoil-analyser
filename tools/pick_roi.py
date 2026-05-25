"""Interactive ROI picker - find exact pixel ROIs for any clip to feed the CLI.

The CLI takes ROIs as ``X Y W H`` pixel boxes (e.g. ``--ammo 2348 1178 125 67``).
This opens a clip's first frame, lets you drag each box, and prints the matching
flags so you can copy them straight into a ``recoil_analyser.cli`` command. ROI
framing matters: a box that's too loose (extra background, casings, smoke) can
push borderline OCR frames into misreads, so draw tight on the target.

Run from the repo root (or anywhere):
    python tools/pick_roi.py data/AKM.mp4              # picks tag + ammo
    python tools/pick_roi.py data/AKM.mp4 ammo                   # just the ammo box
    python tools/pick_roi.py data/AKM.mp4 tag ammo muzzle box    # pick several

Drag a rectangle in each popup, ENTER to confirm, ESC to skip that one.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root importable

import argparse

import cv2

from recoil_analyser.gui import ROI_HELP
from recoil_analyser.roi_select import first_frame, select_roi_scaled

TITLES = {
    "tag": "Select WALL TAG",
    "ammo": "Select AMMO COUNTER",
    "muzzle": "Select MUZZLE",
    "box": "Select BLACK BOX",
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video", help="path to the clip")
    p.add_argument(
        "rois", nargs="*", choices=["tag", "ammo", "muzzle", "box"],
        help="which ROIs to pick (default: tag ammo)",
    )
    args = p.parse_args(argv)

    if not args.rois:
        args.rois = ["tag", "ammo"]

    frame = first_frame(args.video)
    stem = Path(args.video).stem
    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)

    flags: list[str] = []
    for name in args.rois:
        roi = select_roi_scaled(frame, TITLES[name], instructions=ROI_HELP[name])
        if roi is None:
            print(f"  {name}: skipped")
            continue
        x, y, w, h = roi
        print(f"  --{name} {x} {y} {w} {h}")
        flags.append(f"--{name} {x} {y} {w} {h}")
        preview = out_dir / f"roi_{stem}_{name}.png"
        cv2.imwrite(str(preview), frame[y : y + h, x : x + w])
        print(f"       preview -> {preview}")

    if flags:
        print("\nCLI command:")
        print(f"  python -m recoil_analyser.cli --video {args.video} {' '.join(flags)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
