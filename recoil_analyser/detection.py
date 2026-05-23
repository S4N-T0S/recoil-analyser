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


def launch_sample_frames(
    aim: np.ndarray,
    shot_frames: list[int],
    rest_speed: float = 1.5,
    max_lookback: int = 15,
    min_kick_px: float = 10.0,
) -> list[int]:
    """Pick the frame whose aim to sample for each shot (the trigger-pull aim).

    A bullet leaves the muzzle pointed wherever the crosshair sat *before* the
    recoil kick moved the view - but the ammo-counter HUD (what we detect shots
    from) only ticks once the round is gone, a variable 1-5 frames into the kick.
    Sampling at the detected frame therefore records a point partway up the kick,
    and frame-timing jitter scatters it differently each shot. This is invisible
    on steady weapons (the view barely moves in one frame) but wrecks the pattern
    of violent-kick weapons like revolvers, which the gun fully recovers from
    between shots so every bullet truly lands in the same spot.

    Fix: if the view is moving at the detected frame (per-frame speed above
    ``rest_speed``), walk back up to ``max_lookback`` frames - but never past the
    previous shot - to the last frame where it was *settled* (speed at/below
    ``rest_speed``); that is where the trigger was pulled. If no settled frame is
    found (continuous full-auto fire never comes to rest between shots), the
    detected frame is kept. ``rest_speed`` sits well above the sub-pixel jitter
    of a parked view yet far below a kick's onset (which starts at several
    px/frame), so the two are cleanly separated.

    The correction is applied all-or-nothing per weapon, gated on the typical
    walk-back *distance*: only a violent kick that the gun fully recovers from
    moves the view far enough that the ammo tick lands a big jump away from the
    firing aim (revolver ~140px, BFR ~15px). Steadier weapons - including
    full-auto, bursts, and ordinary semis (a DMR walks back <10px) - have the
    detected frame at or near the firing aim already, so if the median walk-back
    is below ``min_kick_px`` the clip is left unchanged at its detected frames.
    """
    if not shot_frames or len(aim) < 2:
        return list(shot_frames)

    speed = np.zeros(len(aim))
    speed[1:] = np.linalg.norm(np.diff(aim, axis=0), axis=1)

    out: list[int] = []
    for k, f in enumerate(shot_frames):
        if speed[f] <= rest_speed:  # already settled at the detected frame
            out.append(f)
            continue
        lo = max(shot_frames[k - 1] + 1 if k > 0 else 0, f - max_lookback)
        i = f
        while i > lo and speed[i] > rest_speed:
            i -= 1
        out.append(i if speed[i] <= rest_speed else f)

    if len(shot_frames) > 1:
        moved = [float(np.linalg.norm(aim[f] - aim[s])) for f, s in zip(shot_frames, out)]
        if float(np.median(moved)) <= min_kick_px:
            return list(shot_frames)
    return out


@dataclass
class RpmEstimate:
    rpm: float | None  # from total span (least quantization error)
    rpm_median: float | None  # from median inter-shot interval
    rpm_max: float | None  # mechanical max: from the tightest cluster of shortest intervals
    n_shots: int
    intervals_frames: list[int] = field(default_factory=list)
    mean_interval_frames: float | None = None
    std_interval_frames: float | None = None
    mechanical_interval_frames: float | None = None
    n_intervals_used: int | None = None  # intervals that fed rpm_max


# An interval counts as the weapon's mechanical cadence (not a human-controlled
# pause between bursts/clicks) if it is within this factor of the fastest
# observed cadence. Burst-internal / capped-semi gaps cluster tightly near the
# floor; the human pauses between them are far larger, so 1.4x cleanly separates
# them while still tolerating +/-1 frame quantization at 120 fps.
_CADENCE_TOL = 1.4


def estimate_rpm(shot_frames: list[int], fps: float) -> RpmEstimate:
    """Estimate rate of fire (rounds/min) from shot frame indices.

    Three figures are reported because they answer different questions:

    * ``rpm`` (span) and ``rpm_median`` assume a *constant* fire rate across the
      whole magazine. They are correct for full-auto but misleading for burst or
      mashed-semi fire, where long human-controlled gaps sit between shots.
    * ``rpm_max`` is the weapon's mechanical ceiling: the rate implied by the
      tightest cluster of *shortest* intervals. The gun cannot fire faster than
      this regardless of input, so within-burst shots (or a mashed semi hitting
      its cap) all land at this cadence while human pauses are discarded. For
      full-auto every interval is in the cluster, so it collapses to ``rpm``.

    The span form ``60 * fps * (n-1) / (last - first)`` spreads the +/-1 frame
    quantization error of a 120 fps capture across the whole burst.
    """
    n = len(shot_frames)
    if n < 2:
        return RpmEstimate(rpm=None, rpm_median=None, rpm_max=None, n_shots=n)

    frames = sorted(shot_frames)
    span = frames[-1] - frames[0]
    rpm_span = 60.0 * fps * (n - 1) / span if span > 0 else None

    intervals = [frames[i + 1] - frames[i] for i in range(n - 1)]
    arr = np.asarray(intervals, dtype=np.float64)
    median_int = float(np.median(arr))
    rpm_median = 60.0 * fps / median_int if median_int > 0 else None

    # Mechanical cadence: reference the low end robustly (10th pct shrugs off a
    # single spuriously short interval), then average the cluster within tol.
    ref = float(np.percentile(arr, 10)) if arr.size >= 5 else float(arr.min())
    cluster = arr[arr <= ref * _CADENCE_TOL]
    mech_int = float(np.mean(cluster)) if cluster.size else None
    rpm_max = 60.0 * fps / mech_int if mech_int and mech_int > 0 else None

    return RpmEstimate(
        rpm=rpm_span,
        rpm_median=rpm_median,
        rpm_max=rpm_max,
        n_shots=n,
        intervals_frames=intervals,
        mean_interval_frames=float(np.mean(arr)),
        std_interval_frames=float(np.std(arr)),
        mechanical_interval_frames=round(mech_int, 3) if mech_int else None,
        n_intervals_used=int(cluster.size) if cluster.size else None,
    )
