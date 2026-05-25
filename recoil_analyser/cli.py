"""Headless command-line entry point.

Example:
    python -m recoil_analyser.cli --video data/akm.mp4 \\
        --weapon AKM --magazine 34 \\
        --tag 60 110 240 90 --ammo 2360 1320 150 60

If --tag / --ammo are omitted you'll be prompted to draw them on the first
frame (same picker the GUI uses).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __author__, __url__, __version__, __website__
from .deps import (
    dependency_error_message,
    missing_dependencies,
    missing_ocr_dependencies,
    ocr_dependency_error_message,
)


def _progress(done: int, total: int) -> None:
    if total:
        pct = 100 * done / total
        print(f"\r  processing frame {done}/{total} ({pct:5.1f}%)", end="", flush=True)
    else:
        print(f"\r  processing frame {done}", end="", flush=True)


def _cli_review(problems, crops, readings, texts) -> dict:
    """Show each flagged crop and prompt for the true count in the terminal.

    Returns {frame: corrected_count_or_None}. The crop is shown in an OpenCV
    window (best-effort - skipped if no display); type the current ammo number
    you see, or just press Enter to mark it unreadable.
    """
    from .ocr import parse_reading

    try:
        import cv2
    except Exception:
        cv2 = None

    print(
        f"\n{len(problems)} OCR frame(s) need confirming. Type the current ammo "
        "number shown in each crop, or press Enter if it's unreadable.\n"
    )
    result: dict[int, int | None] = {}
    for f in problems:
        win = f"frame {f} - ammo crop"
        if cv2 is not None:
            try:
                disp = cv2.resize(crops[f], None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
                cv2.imshow(win, disp)
                cv2.waitKey(1)
            except Exception:
                cv2 = None
        try:
            s = input(f"  frame {f:4d}  (OCR read {texts[f]!r}) -> value: ").strip()
        except EOFError:
            s = ""
        if cv2 is not None:
            try:
                cv2.destroyWindow(win)
                cv2.waitKey(1)
            except Exception:
                pass
        result[f] = parse_reading(s, None)  # forgiving: "0", "0/30", "30/30"
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="recoil_analyser",
        description="Extract recoil pattern from footage.",
        epilog=f"recoil-analyser v{__version__}  -  by {__author__} ({__website__})  -  {__url__}",
    )
    p.add_argument("--video", required=True, help="path to the .mp4 clip")
    p.add_argument("--weapon", default="Unknown")
    p.add_argument("--magazine", type=int, default=None, help="rounds per magazine (improves shot detection)")
    p.add_argument("--method", choices=["ammo", "muzzle", "ocr"], default="ocr")
    p.add_argument("--tag", type=int, nargs=4, metavar=("X", "Y", "W", "H"))
    p.add_argument("--ammo", type=int, nargs=4, metavar=("X", "Y", "W", "H"))
    p.add_argument("--muzzle", type=int, nargs=4, metavar=("X", "Y", "W", "H"))
    p.add_argument("--box", type=int, nargs=4, metavar=("X", "Y", "W", "H"))
    p.add_argument("--fov", type=float, default=81.0)
    p.add_argument("--fov-axis", choices=["horizontal", "vertical", "diagonal"], default="vertical")
    p.add_argument("--distance", type=float, default=13.0)
    p.add_argument("--search-margin", type=int, default=220)
    p.add_argument(
        "--review", action=argparse.BooleanOptionalAction, default=True,
        help="OCR method: prompt to confirm each problem frame (default on; "
        "auto-skipped when stdin isn't interactive). Use --no-review to disable.",
    )
    p.add_argument("--no-audio", action="store_true")
    p.add_argument("--no-plot", action="store_true")
    p.add_argument("--no-trajectory", action="store_true", help="omit per-frame trajectory from JSON")
    p.add_argument("--out", default=None, help="output JSON path (default: output/<video>_<weapon>.json)")
    return p


def _maybe_pick(args) -> tuple[tuple, tuple | None, tuple | None, tuple | None]:
    """Resolve ROIs, prompting interactively for any required ones missing."""
    tag = tuple(args.tag) if args.tag else None
    ammo = tuple(args.ammo) if args.ammo else None
    muzzle = tuple(args.muzzle) if args.muzzle else None
    box = tuple(args.box) if args.box else None

    need_pick = tag is None or (args.method in ("ammo", "ocr") and ammo is None) or (
        args.method == "muzzle" and muzzle is None
    )
    if need_pick:
        from .roi_select import first_frame, select_roi_scaled

        from .gui import ROI_HELP

        frame = first_frame(args.video)
        if tag is None:
            print("Draw a box around the WALL TAG, then press ENTER (ESC to skip).")
            tag = select_roi_scaled(frame, "Select WALL TAG", instructions=ROI_HELP["tag"])
            if tag is None:
                sys.exit("A tag ROI is required.")
        if args.method in ("ammo", "ocr") and ammo is None:
            print("Draw a box around the AMMO COUNTER number, then press ENTER.")
            ammo = select_roi_scaled(frame, "Select AMMO COUNTER", instructions=ROI_HELP["ammo"])
        if args.method == "muzzle" and muzzle is None:
            print("Draw a box around the MUZZLE/front-sight area, then press ENTER.")
            muzzle = select_roi_scaled(frame, "Select MUZZLE", instructions=ROI_HELP["muzzle"])
    return tag, ammo, muzzle, box


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    missing = missing_dependencies()
    if missing:
        print(dependency_error_message(missing), file=sys.stderr)
        return 1

    if args.method == "ocr":
        missing_ocr = missing_ocr_dependencies()
        if missing_ocr:
            print(ocr_dependency_error_message(missing_ocr), file=sys.stderr)
            return 1

    # Imported here so the dependency check above runs first
    from .core import AnalysisConfig, analyse
    from .export import save_json, save_plot

    print(f"S4NT0S recoil-analyser v{__version__}  -  {__website__}\n")
    tag, ammo, muzzle, box = _maybe_pick(args)

    cfg = AnalysisConfig(
        video_path=args.video,
        tag_roi=tag,
        weapon=args.weapon,
        magazine=args.magazine,
        shot_method=args.method,
        ammo_roi=ammo,
        muzzle_roi=muzzle,
        box_roi=box,
        fov_deg=args.fov,
        fov_axis=args.fov_axis,
        distance_m=args.distance,
        search_margin=args.search_margin,
        use_audio=not args.no_audio,
        progress=_progress,
        review=_cli_review if (args.method == "ocr" and args.review and sys.stdin.isatty()) else None,
    )

    print(f"Analysing {args.video} ...")
    result = analyse(cfg)
    print()  # newline after progress

    stem = Path(args.video).stem
    out_json = Path(args.out) if args.out else Path("output") / f"{stem}_{args.weapon}.json"
    save_json(result, out_json, include_trajectory=not args.no_trajectory)
    print(f"  wrote {out_json}")

    if not args.no_plot:
        png = out_json.with_suffix(".png")
        if save_plot(result, png):
            print(f"  wrote {png}")

    d = result.data
    print(
        f"\nDone: {d['shots_detected']} shots, "
        f"RPM~{d['rpm']['video_span']} (mech. max ~{d['rpm']['mechanical_max']}), "
        f"min tracking confidence {d['tracking']['min_confidence']:.3f}"
    )

    ocr = d.get("ocr")
    if ocr:
        print(
            f"  OCR: read {ocr['frames_read']}/{ocr['frames_total']} frames, "
            f"score min/mean {ocr['min_score']}/{ocr['mean_score']}"
        )
        if ocr["shots_match_magazine"] is False:
            print(
                f"  WARNING: detected {d['shots_detected']} shots but magazine is "
                f"{d['magazine']} - check the ammo ROI / magazine size."
            )
        if ocr["over_magazine_rejected"]:
            print(
                f"  WARNING: {ocr['over_magazine_rejected']} frame(s) read a number "
                "above the magazine and were discarded."
            )
        if result.ocr_series is not None:
            from .ocr import transcript_lines

            print("\nOCR transcript (frames where the reading changed):")
            for line in transcript_lines(result.ocr_series, result.shot_frames, d["magazine"]):
                print("  " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
