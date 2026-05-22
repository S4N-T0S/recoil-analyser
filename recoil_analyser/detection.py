"""Shot detection and rate-of-fire estimation.

Two independent visual cues are supported, both reduced to a per-frame 1-D
signal whose peaks mark shots:

* **ammo**  - mean absolute frame-to-frame change inside the HUD ammo-counter
              ROI. The digit changes the instant a round is consumed, so the
              count is exact and the timing is locked to the HUD.
* **muzzle**- mean brightness inside a muzzle ROI; each shot is a bright flash.

Because the magazine size is known, we keep the ``n_expected`` strongest peaks,
which makes detection robust to threshold choice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def find_peaks(
    signal: np.ndarray,
    min_gap: int = 3,
    n_expected: int | None = None,
    rel_threshold: float = 0.25,
) -> list[int]:
    """Return frame indices of peaks in ``signal``.

    Args:
        signal:      1-D per-frame signal (>= 0 is assumed for thresholding).
        min_gap:     minimum number of frames between two accepted peaks.
        n_expected:  if given, return exactly the strongest ``n_expected`` peaks
                     (subject to ``min_gap``); the relative threshold is ignored.
        rel_threshold: when ``n_expected`` is None, keep peaks above
                     ``rel_threshold * max(signal)``.
    """
    signal = np.asarray(signal, dtype=np.float64)
    if signal.size == 0:
        return []

    # Candidate local maxima: a point at least as large as both neighbours.
    candidates: list[int] = []
    for i in range(signal.size):
        left = signal[i - 1] if i > 0 else -np.inf
        right = signal[i + 1] if i < signal.size - 1 else -np.inf
        if signal[i] >= left and signal[i] >= right and signal[i] > 0:
            candidates.append(i)

    # Greedily accept peaks strongest-first, enforcing the minimum gap.
    candidates.sort(key=lambda i: signal[i], reverse=True)
    accepted: list[int] = []
    for i in candidates:
        if all(abs(i - j) >= min_gap for j in accepted):
            accepted.append(i)

    if n_expected is not None:
        accepted = sorted(accepted, key=lambda i: signal[i], reverse=True)[:n_expected]
    else:
        floor = rel_threshold * float(signal.max())
        accepted = [i for i in accepted if signal[i] >= floor]

    return sorted(accepted)


def find_shot_frames(
    signal: np.ndarray,
    n_expected: int | None = None,
    min_gap: int = 3,
) -> list[int]:
    """Robust shot-frame detection with an adaptive minimum gap.

    A first pass finds the strongest ``n_expected`` peaks. Because the rate of
    fire is constant within a burst, we then estimate the typical inter-shot
    spacing from that pass and re-detect with ``min_gap`` raised to ~half the
    median spacing. This suppresses spurious double-detections (a HUD redraw or
    muzzle smoke can split one shot into two close peaks) and frees up slots for
    the genuine, weaker peaks that would otherwise be crowded out.
    """
    peaks = find_peaks(signal, min_gap=min_gap, n_expected=n_expected)
    if n_expected and len(peaks) >= 4:
        intervals = np.diff(peaks)
        median_int = float(np.median(intervals))
        adaptive = max(min_gap, int(round(median_int * 0.55)))
        if adaptive > min_gap:
            peaks = find_peaks(signal, min_gap=adaptive, n_expected=n_expected)
    return peaks


@dataclass
class RpmEstimate:
    rpm: float | None  # from total span (least quantization error)
    rpm_median: float | None  # from median inter-shot interval
    n_shots: int
    intervals_frames: list[int] = field(default_factory=list)
    mean_interval_frames: float | None = None
    std_interval_frames: float | None = None


def estimate_rpm(shot_frames: list[int], fps: float) -> RpmEstimate:
    """Estimate rate of fire (rounds/min) from shot frame indices.

    The span form ``60 * fps * (n-1) / (last - first)`` spreads the +/-1 frame
    quantization error of a 120 fps capture across the whole burst, so it is far
    more accurate than averaging individual intervals.
    """
    n = len(shot_frames)
    if n < 2:
        return RpmEstimate(rpm=None, rpm_median=None, n_shots=n)

    frames = sorted(shot_frames)
    span = frames[-1] - frames[0]
    rpm_span = 60.0 * fps * (n - 1) / span if span > 0 else None

    intervals = [frames[i + 1] - frames[i] for i in range(n - 1)]
    median_int = float(np.median(intervals))
    rpm_median = 60.0 * fps / median_int if median_int > 0 else None

    return RpmEstimate(
        rpm=rpm_span,
        rpm_median=rpm_median,
        n_shots=n,
        intervals_frames=intervals,
        mean_interval_frames=float(np.mean(intervals)),
        std_interval_frames=float(np.std(intervals)),
    )
