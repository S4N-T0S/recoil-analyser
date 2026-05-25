# S4NT0S Recoil Analyser

Extracts a weapon's **recoil pattern** from a gameplay clip and exports it to
JSON. Recoil is measured by tracking a fixed
feature on the wall you fire at: as the gun kicks the *view* up/right, that wall
feature slides the opposite way on screen, so its motion (negated) **is** the
recoil trajectory.

It also reports the weapon's **rate of fire (RPM)** and the recoil in three
units: screen pixels, view degrees, and centimetres on the wall.

> The defaults (FOV 81 vertical, 13 m, AKM/34) are tuned for **The Finals**, but
> the method is game-agnostic — it works for **any first-person shooter** once
> you set the FOV, wall distance, magazine size and ROIs for your game.

![S4NT0S Recoil Analyser GUI](docs/gui.png)

---

## How to record footage (read this first)

The analysis is only as good as the clip. Follow this protocol:

1. **Stand ~13 m from a flat white wall** (the practice range works well). Keep
   the distance consistent between recordings — it's used for the cm figures.
2. **Put a small high-contrast sticker/tag on the wall**, ideally toward a
   corner of the screen (top-left in the reference clip) so it never collides
   with the crosshair or muzzle flash. This tag is the primary tracking target,
   so it must stay **fully in frame for the whole burst** — recoil moves it, so
   leave margin in the direction the gun climbs (usually downward on screen).
3. **Fire with a keyboard bind, not the mouse**, so the only view movement is
   recoil — never accidental aim input. Do **not** move the mouse while firing.
4. **Empty the full magazine** in one continuous burst at the wall.
5. **Capture settings** (what the tool is tuned for):
   - 1440p (2560×1440), **120 FPS** — high FPS gives accurate per-shot timing.
   - Default **FOV 81** (The Finals reports a *vertical* FOV), native resolution.
   - All **textures / detail / anti-aliasing on LOW/off** — less visual noise
     means cleaner tracking.
   - Near-lossless capture (e.g. OBS **CQP** ~14).
   - **Keep the audio track** if you want an independent RPM cross-check.
6. **Trim the clip tightly**: first frame = full mag shown, *no shot yet*; the
   next frame is the first shot; end a handful of frames after the last shot.
   (Reference clip: AKM, 34 rounds, 403 frames — frame 0 = `34/34`, frame 1 =
   first shot, ends ~6 frames after the last round.)

   To cut **frame-accurately without re-encoding** (so quality is untouched and
   it's instant), use **[LosslessCut](https://github.com/mifi/lossless-cut#download)**
   — a free, open-source trimmer. Open the recording, step frame-by-frame (using **,** and **.**) to the
   frame *just before* the first shot, set the start there; set the end a few
   frames after the last shot; export. Because it stream-copies rather than
   re-encodes, the output stays at your original CQP quality.

**Resolution and frame rate are auto-detected** from the file — no code edits
needed for 1080p or 60 fps. **1440p / 120 fps is recommended**
though: a higher frame rate makes RPM and per-shot timing more precise. Note that
raw pixel values scale with resolution, so to compare recoil across different
captures use the resolution-independent **degrees / cm** fields rather than
`x`/`y` pixels.

Put clips in `data/`. Exports land in `output/`.

### Example clip & drawing reference image

A trimmed example lives at **`data/AKM.mp4`** (compressed). Use it to see exactly how a
clip should look and be cut. Please do not compress your analysis clips.

![How to draw the tag / ammo / box ROIs](docs/roi_guide.png)

https://github.com/user-attachments/assets/74446ccb-1aac-4eb2-8659-dffad226b1d3

---

## Install

Requires **Python 3.13** (3.11/3.12 also work — but **not 3.14**: PaddleOCR's
`paddlepaddle` backend has no 3.14 wheels yet). **ffmpeg** on `PATH` is optional,
used only for the audio RPM cross-check.

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

If you don't already have Python 3.13, [`uv`](https://docs.astral.sh/uv/) sets it
up in one step without touching your system Python:

```bash
uv venv --python 3.13
uv pip install -r requirements.txt
```

> **First OCR run downloads a model** (~85 MB, once) to `~/.paddlex`, so the
> `ocr` shot-detection method needs internet the first time. The `ammo` and
> `muzzle` methods work fully offline.

---

## Usage

### GUI (recommended)

```bash
python -m recoil_analyser

# OR if you're using UV

uv run python -m recoil_analyser
```

1. Browse to your clip, pick the weapon (sets magazine size), set FOV / distance.
2. Click **Select regions & analyse**. A popup shows the first frame with
   **on-image instructions** for each region you draw:
   - the **wall tag** (required),
   - the **ammo counter** number (for the `ammo`/`ocr` shot-detection methods), and
   - optionally the **black box** crate (a second reference for a sanity check).
   Drag a rectangle, press **ENTER** to confirm, **ESC** to cancel/skip.
3. With **"ask me about OCR issues"** ticked (default), any frame the OCR
   couldn't read confidently or that disagrees with the countdown is shown to
   you - the crop plus its guess - so you can type the correct number before the
   result is finalised. Untick it to skip review.
4. It writes `output/<clip>_<weapon>.json` + a `.png` plot and shows a summary.
   With the OCR method it also opens a window listing what it read at each
   frame, with shots and any discarded misreads flagged.

**How tightly to draw:** include the whole tag plus a *little* margin — a bit of
white wall around it is fine and even helps. The box does **not** need to hug
the tag's edges. The only hard rule: never include things that move differently
from the wall (the crosshair, the gun model, the muzzle flash). For the optional
crate, pick a small high-contrast corner *on* the crate rather than the whole
object — a huge ROI tracks worse.

The picker shows a down-scaled view of the 1440p frame and maps your selection
back to full resolution automatically.

### CLI (headless / scriptable)

```bash
python -m recoil_analyser.cli \
    --video data/AKM.mp4 --weapon AKM --magazine 34 \
    --tag 60 110 240 90 --ammo 2370 1185 175 60 \
    --box 90 470 520 380          # optional
```

Omit `--tag` / `--ammo` to be prompted to draw them. Useful flags:
`--method {ocr,ammo,muzzle}` (default `ocr`), `--fov 81`, `--fov-axis vertical`,
`--distance 13`, `--no-audio`, `--no-plot`, `--no-trajectory`, `--out path.json`.
For the OCR method, `--review` (default on, `--no-review` to disable) prompts you
to confirm each problem frame — it shows the crop and asks for the number; it
auto-skips when stdin isn't a terminal, so scripted/batch runs never block.
For the OCR method the CLI also prints a per-frame transcript of what it read
(frames where the reading changed), so you can eyeball any misreads.

---

## How it works

| Step | Method |
| --- | --- |
| **Tracking** | Sub-pixel template matching (normalised cross-correlation) of the frame-0 tag against every frame, refined by a parabolic fit on the correlation peak. Always matched against frame 0, so it never drifts. The gun model, weapon sway and FOV "punch" are ignored because we track the *wall*, not the gun. |
| **Aim trajectory** | `aim = −(tag_position − tag_position_at_frame_0)`. Pure view rotation moves every world point by the same number of pixels, so the tag's screen motion equals the aim point's motion (negated). |
| **Shot detection** | *ocr* (default): reads the ammo count every frame with PaddleOCR (server recognition model) on the plain cropped HUD region and registers a shot the frame the count first decrements; a min-run-length rule drops single-frame misreads and a single-unit-decrement rule stops a digit misread (e.g. "11" read as "1") from inflating the shot count; and quick-reload weapons that snap the HUD back to a full count without ever showing "0" (e.g. ARN-220) still get their final round registered. Handles both `N/M` current-over-magazine HUDs (The Finals, Counter Strike, Overwatch, Marvel Rivals) and bare current-count HUDs that show no magazine (e.g. Apex Legends); setting `--magazine` adds a sanity cap that also rejects slash misreads but isn't required. It is the most robust cue — it reads through muzzle smoke, tracers and shell casings drifting across the ROI, which can fool the simpler methods below. *ammo*: per-frame change inside the ammo-counter ROI spikes when a round is consumed; we keep the strongest `magazine` peaks (lighter, but background motion behind the counter can register as false shots). *muzzle*: brightness peaks in a muzzle ROI. All three resolve to the same shot frames, so the trigger-pull sampling, RPM and pattern below are identical regardless of method. |
| **Trigger-pull sampling** | The ammo HUD ticks a variable 1–5 frames *after* the round leaves, so on a violent-kick weapon the detected frame is already partway up the kick. For weapons that fully recover between shots (revolvers), each bullet is therefore sampled at the last settled frame before its kick — where the trigger was actually pulled — instead of the detected frame. Continuous-fire weapons are sampled at the detected frame unchanged. `pattern[].sample_frame` reports which frame was used. |
| **RPM** | `video_span` = `60 · fps · (n−1) / (last_shot_frame − first_shot_frame)` (total-span form minimises 120 fps quantization error) — correct for full-auto. `mechanical_max` derives the weapon's mechanical ceiling from the tightest cluster of *shortest* inter-shot intervals, so it recovers the true rate for **burst and semi-auto** weapons where the span/median average in human-controlled gaps. Audio onset detection (via ffmpeg) provides an independent cross-check. |
| **Units** | Pinhole model: `focal_px = (axis_size/2) / tan(fov/2)` where `axis_size` is the height for a vertical FOV (The Finals' default) or width for horizontal; degrees `= atan(Δpx / focal_px)`; cm on wall `= distance · Δpx / focal_px`. |

### Coordinate convention

Screen pixels, **+x = right, +y = down**. A normal upward kick therefore shows
as **negative y**. The per-bullet `pattern` is relative to bullet 1 (so
bullet 1 = `0, 0`); the full per-frame `trajectory` is included for animation.
`time_s` is relative to the first shot (bullet 1 = `0.0`; frames before it are
negative), while `frame` stays the absolute index into the video file.

---

## Output JSON

```jsonc
{
  "weapon": "AKM",
  "capture": { "fps": 120, "width": 2560, "height": 1440,
               "fov_deg": 81, "fov_axis": "vertical",
               "distance_m": 13, "focal_px": 842.6 },
  "magazine": 34,
  "shots_detected": 34,
  "recoil_class": "standard",        // or "recovers_between_shots" (revolver-class)
  "pattern_spread_px": { "x": 41.1, "y": 245.6, "max": 245.6 },
  "rpm": { "video_span": 720.0, "video_median": 720.0,
           "mechanical_max": 720.0,      // weapon's ceiling (matters for burst/semi)
           "audio": 718.4, "intervals_frames": [10, 10, ...] },
  "tracking": { "feature": "tag", "min_confidence": 0.97,
                "box_crosscheck": { "mean_abs_diff_px": 0.4 } },
  "ocr": {                           // only when --method ocr (else null)
    "model": "PP-OCRv5_server_rec", // default engine, can be changed to another if you experience issues
    "frames_read": 475, "frames_total": 475,
    "min_score": 0.74, "mean_score": 0.96,  // PaddleOCR recognition confidence
    "over_magazine_rejected": 0,            // reads above the magazine, discarded
    "reviewed_frames": 0,                   // frames you corrected in review
    "shots_match_magazine": true            // detected shots == magazine?
  },
  "pattern": [                       // one entry per bullet, relative to bullet 1
    { "bullet": 1, "frame": 1,  "sample_frame": 1,  "time_s": 0.0, "x": 0.0,  "y": 0.0,
      "dx_deg": 0.0,  "dy_deg": 0.0,  "dx_cm": 0.0,  "dy_cm": 0.0 },
    { "bullet": 2, "frame": 11, "sample_frame": 11, "time_s": 0.083, "x": -4.9, "y": -19.8,
      "dx_deg": -0.19, "dy_deg": -0.76, "dx_cm": -4.3, "dy_cm": -17.2 }
  ],
  "trajectory": [ { "frame": 0, "time_s": -0.008, "x": 0.0, "y": 0.0,
                    "confidence": 1.0 }, ... ]   // per-frame view path
}
```

`tracking.min_confidence` is your quality gauge — values near 1.0 mean the tag
was tracked cleanly. If it drops (e.g. the tag left frame or motion blur), the
affected bullets are suspect. The `box_crosscheck` compares the recoil derived
from the box against the tag; a large difference points to parallax/translation
or a tracking failure.

`recoil_class` is `"recovers_between_shots"` when the weapon fully recovers to
the same aim between shots (revolver-class). For these the pattern is
effectively zero and `pattern_spread_px.max` is the residual measurement floor
(see *Known limitations*), not real recoil — a consumer can label them
"≈ no recoil (±N px)". Everything else is `"standard"`.

The `ocr` block (present only for `--method ocr`) is your read-quality gauge.
`mean_score` / `min_score` are PaddleOCR's per-frame recognition confidence
(near 1.0 is healthy). `shots_match_magazine: false` or a non-zero
`over_magazine_rejected` are red flags that the ammo ROI or magazine size is off
— both are also printed as warnings in the CLI/GUI summary.

---

## Known limitations

**Violent-recoil weapons that fire before fully recovering (~±5 px floor).**
Revolver-class weapons have no real recoil — every bullet lands in the same
spot — and the analyser confirms this to within a few px (`recoil_class:
"recovers_between_shots"`). The residual depends on fire rate: the slow BFR TITAN
(~70 RPM) fully settles between shots and reads ~1 px, while a faster revolver
(~140 RPM) fires while the view is still creeping through the last few px of
recovery and reads ~4 px of phantom drift. This is *rendered-view lag*, not
recoil: the game points the bullet at the true crosshair while the wall-view we
track hasn't finished settling. The same few-px uncertainty exists on automatic
weapons but is negligible against their 100–500 px patterns. Treat
`pattern_spread_px` on a `recovers_between_shots` weapon as a noise floor.

---

## Validation

`tools/validate.py` renders a synthetic clip with a *known* injected recoil
pattern, runs the analyser, and asserts the recovered pattern, shot frames and
RPM match. Current recovery error is ~0.02 px.

```bash
python tools/validate.py
```

---

## Project layout

```
recoil_analyser/
  geometry.py    px ↔ degrees ↔ cm (pinhole model)
  tracking.py    sub-pixel template tracker
  detection.py   shot detection + RPM from frames
  ocr.py         PaddleOCR ammo-counter reader (--method ocr)
  audio.py       optional audio-onset RPM (ffmpeg)
  core.py        single-pass analysis → result dict
  export.py      JSON + matplotlib plot
  roi_select.py  scaled cv2.selectROI helper
  gui.py         Tkinter front-end
  cli.py         argparse front-end
tools/           synthetic test video + validation
data/            raw clips (git-ignored, except example AKM.mp4)
output/          exports (git-ignored)
```

---

## License & credits

© 2026 **[S4N-T0S](https://s4nt0s.eu)** — released under the
[MIT License](LICENSE).

Author: **https://s4nt0s.eu**  ·  Source: **https://github.com/S4N-T0S/recoil-analyser**

Built with [OpenCV](https://opencv.org/), [NumPy](https://numpy.org/),
[Matplotlib](https://matplotlib.org/) and [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR);
clip trimming via [LosslessCut](https://github.com/mifi/lossless-cut).
