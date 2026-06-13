"""EEG windowing -- slice continuous EEG into fixed-length windows.

This module provides windowing for the offline NPZ path.
For real-time LSL path, use lsl_buffer.EEGRollingBuffer instead.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import EEGWindow


def iter_eeg_windows(
    eeg: np.ndarray,
    sample_rate: float,
    window_seconds: float = 2.0,
    step_seconds: float = 0.5,
    unit: str = "counts",
    gain: float = 24.0,
    vref: float = 4.5,
) -> Iterator[EEGWindow]:
    """Slice continuous EEG into fixed-length overlapping windows.

    Args:
        eeg: Continuous EEG data, shape (channels, samples).
        sample_rate: Sampling rate in Hz.
        window_seconds: Window length in seconds (default 2.0).
        step_seconds: Step size in seconds (default 0.5).
        unit: Data unit, "counts" or "uv".
        gain: ADS1299 gain for counts->uV conversion.
        vref: ADS1299 reference voltage for counts->uV conversion.

    Yields:
        EEGWindow objects with shape (channels, window_samples).

    Note:
        If data is shorter than one window, no windows are yielded.
        This module does not perform any unit conversion.
    """
    n_channels, n_samples = eeg.shape
    window_samples = int(window_seconds * sample_rate)
    step_samples = int(step_seconds * sample_rate)

    if n_samples < window_samples:
        return

    start = 0
    while start + window_samples < n_samples:
        data = eeg[:, start : start + window_samples].astype(np.float64)
        yield EEGWindow(
            data=data,
            sample_rate=sample_rate,
            start_sample=start,
            start_time=start / sample_rate,
            unit=unit,
            gain=gain,
            vref=vref,
        )
        start += step_samples
