"""Ammo-counter OCR shot detection backend (PaddleOCR, CPU).

Each frame the HUD ammo number ("N/M") is read from the ammo ROI with
PaddleOCR's *recognition* model only - text detection is skipped (the user
already boxes the digits), which roughly halves the per-frame cost.

The cropped HUD region is fed to the recogniser **as-is**. An earlier binarising
colour filter was tried and removed: hard thresholding fused adjacent thin
digits (the two 1s of "11" merged into one blob), which the recogniser then read
as "1" - and on a fast weapon that single misread collapsed a whole run of shots
onto one frame. The server recogniser reads the natural colour crop reliably even
with the low-ammo pink/red flash and muzzle smoke / tracers / shell casings
drifting behind the number, so no filtering is needed. The recognised string is
whitelisted to ``0123456789/`` - the only glyphs the counter ever shows.

PaddlePaddle ships no Python 3.14 wheels, so paddleocr is imported lazily here
and only when the OCR method is actually selected; the rest of the tool runs on
3.14 without it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Skip paddle's slow model-hoster connectivity probe; the model is downloaded on demand or already cached under ~/.paddlex.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
# Silence PaddlePaddle's native C++ logging (glog).
os.environ.setdefault("GLOG_minloglevel", "3")
os.environ.setdefault("GLOG_logtostderr", "0")

import logging

import numpy as np

_ALLOWED = frozenset("0123456789/")
_DEFAULT_MODEL = "PP-OCRv5_server_rec"


def parse_reading(text: str, magazine: int | None = None) -> int | None:
    """Parse a recognised string into the current ammo count, or None.

    Handles two HUD styles: "N/M" current-over-magazine (The Finals, most
    shooters) where the count is the numerator left of the slash, and a bare
    "N" current-count-only HUD (e.g. Apex Legends) where the whole reading is
    the count. So a slash is used when present but not required.

    ``magazine``, when known, rejects impossible readings - and crucially
    catches the occasional misread where an "N/M" slash is read as a digit
    ("27/34" -> "27134"): with no slash left to split on, that collapses to a
    number far above the magazine and is discarded. Games that show no
    magazine simply leave it unset; the countdown reconstruction still drops
    single-frame blips and out-of-sequence misreads on its own.
    """
    cleaned = "".join(c for c in text if c in _ALLOWED)
    candidate = cleaned.split("/", 1)[0] if "/" in cleaned else cleaned
    if not candidate.isdigit():
        return None
    value = int(candidate)
    if magazine is not None and value > magazine:
        return None
    return value


@dataclass
class OcrSeries:
    """Per-frame OCR output plus quality signals for confidence reporting."""

    readings: list[int | None]  # parsed current-ammo per frame (None if unusable)
    scores: list[float]  # PaddleOCR recognition score per frame (0-1)
    texts: list[str]  # raw recognised string per frame (kept for the transcript)
    over_magazine: int  # frames whose number exceeded the magazine and were dropped


class AmmoReader:
    """Lazy PaddleOCR recogniser for the ammo HUD number."""

    def __init__(self, model_name: str = _DEFAULT_MODEL, device: str = "cpu") -> None:
        # Quiet paddle's per-call INFO/onednn chatter.
        logging.disable(logging.WARNING)
        from paddleocr import TextRecognition

        self.model_name = model_name
        self._rec = TextRecognition(model_name=model_name, device=device)

    def read_series(
        self,
        crops_bgr: list[np.ndarray],
        magazine: int | None = None,
        batch_size: int = 16,
        progress=None,
    ) -> OcrSeries:
        """Read every crop, in order, with per-frame scores and quality counts.

        ``over_magazine`` counts frames where a clean number was recognised but
        exceeded ``magazine`` (so it was discarded) - typically the slash of an
        "N/M" HUD misread as a digit. A high count is a red flag that the ROI or
        magazine size is wrong; it is surfaced to the user rather than hidden.
        """
        n = len(crops_bgr)
        readings: list[int | None] = [None] * n
        scores: list[float] = [0.0] * n
        texts: list[str] = [""] * n
        over_magazine = 0
        for start in range(0, n, batch_size):
            chunk = crops_bgr[start : start + batch_size]
            for j, out in enumerate(self._rec.predict(chunk, batch_size=batch_size)):
                text = out["rec_text"]
                value = parse_reading(text, magazine)
                readings[start + j] = value
                scores[start + j] = float(out["rec_score"])
                texts[start + j] = text
                if value is None and magazine is not None:
                    raw = parse_reading(text, None)  # re-parse ignoring the cap
                    if raw is not None and raw > magazine:
                        over_magazine += 1
            if progress is not None:
                progress(min(start + batch_size, n), n)
        return OcrSeries(readings=readings, scores=scores, texts=texts, over_magazine=over_magazine)


def transcript_lines(
    series: OcrSeries, shot_frames: list[int], magazine: int | None = None
) -> list[str]:
    """Render a compact per-frame OCR log for after-analysis review.

    Only frames where the recognised text *changes* are emitted (the count
    holds for ~10-30 frames between shots, so this collapses to roughly one
    line per round). Shot frames are tagged with their bullet number and
    discarded frames are flagged so misreads are easy to spot.
    """
    bullet_of = {f: i + 1 for i, f in enumerate(shot_frames)}
    shots = set(shot_frames)
    lines: list[str] = []
    prev: str | None = None
    for i, text in enumerate(series.texts):
        if text == prev:
            continue
        prev = text
        if i in shots:
            note = f"  <- shot {bullet_of[i]}"
        elif series.readings[i] is None:
            raw = parse_reading(text, None)
            note = (
                "  (dropped: over magazine)"
                if raw is not None and magazine is not None and raw > magazine
                else "  (dropped: unreadable)"
            )
        else:
            note = ""
        shown = text if text else "(blank)"
        lines.append(f"frame {i:4d}: {shown:>10}   score {series.scores[i]:.2f}{note}")
    return lines
