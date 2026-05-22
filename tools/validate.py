"""End-to-end validation: generate a known clip, analyse it, compare.

Run from the repo root:  python tools/validate.py
Exits non-zero if the recovered pattern, shot frames, or RPM drift beyond
tolerance.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from recoil_analyser.core import AnalysisConfig, analyse  # noqa: E402
from tools.make_test_video import generate  # noqa: E402

PX_TOL = 1.0  # max per-bullet error allowed (px)


def _check(meta: dict, method: str, roi_kwargs: dict) -> bool:
    cfg = AnalysisConfig(
        video_path=meta["path"],
        tag_roi=tuple(meta["tag_roi"]),
        weapon="TEST",
        magazine=meta["magazine"],
        shot_method=method,
        box_roi=tuple(meta["box_roi"]),
        use_audio=False,
        **roi_kwargs,
    )
    res = analyse(cfg)
    d = res.data

    ok = True
    print(f"\n=== method={method} ===")
    print(f"shots detected: {d['shots_detected']} (expected {meta['magazine']})")
    if d["shots_detected"] != meta["magazine"]:
        print("  FAIL: wrong shot count")
        ok = False

    detected_frames = res.shot_frames
    if detected_frames != meta["shot_frames"]:
        print(f"  shot frames {detected_frames}")
        print(f"  expected    {meta['shot_frames']}")
        # off-by-one on a couple frames is acceptable for muzzle; flag large drift
        if any(abs(a - b) > 1 for a, b in zip(detected_frames, meta["shot_frames"])):
            print("  FAIL: shot-frame drift > 1")
            ok = False
        else:
            print("  (within +/-1 frame - acceptable)")

    print(f"RPM span={d['rpm']['video_span']} median={d['rpm']['video_median']}")
    expected_rpm = 60.0 * meta["fps"] / 8  # interval 8 frames
    if d["rpm"]["video_span"] and abs(d["rpm"]["video_span"] - expected_rpm) > 5:
        print(f"  FAIL: RPM off (expected ~{expected_rpm:.0f})")
        ok = False

    print(f"tracking confidence min/mean: {d['tracking']['min_confidence']:.3f}"
          f" / {d['tracking']['mean_confidence']:.3f}")

    max_err = 0.0
    for got, exp in zip(d["pattern"], meta["expected_pattern"]):
        ex = abs(got["x"] - exp["x"])
        ey = abs(got["y"] - exp["y"])
        max_err = max(max_err, ex, ey)
    print(f"max per-bullet pattern error: {max_err:.3f} px (tol {PX_TOL})")
    if max_err > PX_TOL:
        print("  FAIL: pattern error exceeds tolerance")
        ok = False
        for got, exp in zip(d["pattern"], meta["expected_pattern"]):
            print(f"   b{got['bullet']:>2} got=({got['x']:+.2f},{got['y']:+.2f}) "
                  f"exp=({exp['x']:+.2f},{exp['y']:+.2f})")

    if d["tracking"]["box_crosscheck"]:
        print(f"box cross-check mean diff: "
              f"{d['tracking']['box_crosscheck']['mean_abs_diff_px']} px")
    return ok


def main() -> int:
    print("Generating synthetic clip...")
    meta = generate("output/_synthetic_test.mp4")

    ok_ammo = _check(meta, "ammo", {"ammo_roi": tuple(meta["ammo_roi"])})
    ok_muzzle = _check(meta, "muzzle", {"muzzle_roi": tuple(meta["muzzle_roi"])})

    print("\n========================================")
    print("RESULT:", "PASS" if (ok_ammo and ok_muzzle) else "FAIL")
    return 0 if (ok_ammo and ok_muzzle) else 1


if __name__ == "__main__":
    raise SystemExit(main())
