# tools/

Developer utilities — not needed for normal analysis.

## pick_roi.py

Interactive ROI picker. Used to find exact pixel bounding boxes (Regions of Interest) for a given video clip to feed into the headless CLI or debugging.

The CLI takes ROIs as `X Y W H` pixel boxes (e.g., `--ammo 2348 1178 125 67`). This tool opens a scaled copy of the clip's first frame and lets you draw a box around each requested feature. It then prints the matching command-line flags so you can copy them straight into an analysis command. 

*Note: ROI framing matters. You don't want something too tight.*

```bash
# run from the repo root
uv run python tools/pick_roi.py data/AKM.mp4                     # picks tag + ammo (default)
uv run python tools/pick_roi.py data/AKM.mp4 ammo                # just the ammo box
uv run python tools/pick_roi.py data/AKM.mp4 tag ammo muzzle box # pick several
```

## validate.py

End-to-end accuracy test. It renders a 90-frame synthetic clip at 1280×720 with
a **known, numerically exact recoil pattern** injected into it (world layer
shifted per frame, HUD ammo counter drawn on top, muzzle flash on shot frames),
then runs the full analysis pipeline against it and asserts recovery is within
tolerance.

```bash
# run from the repo root
python tools/validate.py
```

What it checks:

| Check | Expected |
| --- | --- |
| Shots detected | equals magazine size (10) |
| Shot frame timing | exact match (ammo method) or ±1 frame (muzzle method) |
| RPM (video-span formula) | 900 ± 5 rpm |
| Per-bullet pattern error | < 1.0 px (typically ~0.02 px) |
| Box cross-check drift | ~0 px (same shift applied to both features) |

Current results (both detection methods):

```
shots detected: 10/10
RPM span=900.0  median=900.0
tracking confidence min/mean: 0.968 / 0.990
max per-bullet pattern error: 0.017 px
box cross-check mean diff: 0.007 px
PASS
```

### make_test_video.py

Called by `validate.py` — you can also call it directly to inspect the
synthetic clip yourself:

```bash
python tools/make_test_video.py
# writes output/_synthetic_test.mp4
```

Open it and you will see a light-grey wall, a tag in the top-left, a labelled
box on the left, a dark gun in the lower centre, and the ammo counter
decrementing. The world layer slowly drifts upward (simulating recoil up) while
the HUD stays fixed — exactly what a real clip looks like.
