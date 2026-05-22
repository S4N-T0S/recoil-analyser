"""Optional audio-based RPM cross-check.

Gunshots are sharp audio transients. We decode the clip's audio to mono PCM
with ffmpeg, build a short-time energy onset envelope, and pick the strongest
onsets (count known from the magazine) to estimate rate of fire independently
of the video. Returns ``None`` whenever ffmpeg is missing or the clip has no
usable audio, so callers can degrade gracefully.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

import numpy as np


@dataclass
class AudioRpm:
    rpm: float | None
    n_onsets: int
    onset_times_s: list[float]
    sample_rate: int


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _decode_mono_pcm(video_path: str, sample_rate: int) -> np.ndarray | None:
    cmd = [
        "ffmpeg", "-i", video_path,
        "-ac", "1", "-ar", str(sample_rate),
        "-f", "s16le", "-loglevel", "error", "pipe:1",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False)
    except (OSError, ValueError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float64) / 32768.0


def estimate_rpm_from_audio(
    video_path: str,
    n_expected: int,
    sample_rate: int = 22050,
    hop: int = 256,
) -> AudioRpm | None:
    if not ffmpeg_available():
        return None
    samples = _decode_mono_pcm(video_path, sample_rate)
    if samples is None or samples.size < sample_rate // 10:
        return None

    # Short-time RMS energy envelope.
    n_hops = samples.size // hop
    if n_hops < 4:
        return None
    frames = samples[: n_hops * hop].reshape(n_hops, hop)
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)

    # Onset strength = positive change in energy (half-wave rectified).
    onset = np.diff(rms, prepend=rms[0])
    onset = np.maximum(onset, 0.0)

    # Minimum spacing: assume no weapon exceeds ~1500 rpm (= 25 shots/s).
    min_gap_hops = max(1, int((sample_rate / hop) / 25.0))

    from .detection import find_peaks

    peak_hops = find_peaks(onset, min_gap=min_gap_hops, n_expected=n_expected)
    times = [h * hop / sample_rate for h in peak_hops]

    rpm = None
    if len(times) >= 2:
        span = times[-1] - times[0]
        if span > 0:
            rpm = 60.0 * (len(times) - 1) / span

    return AudioRpm(
        rpm=rpm,
        n_onsets=len(times),
        onset_times_s=times,
        sample_rate=sample_rate,
    )
