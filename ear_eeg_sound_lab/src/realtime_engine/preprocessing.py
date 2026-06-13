"""EEG preprocessing — unit conversion, demean, and filtering.

First version: counts→uV (conditional), demean, bandpass 1-45 Hz, notch 50/60 Hz.
Uses scipy for IIR filtering. Does NOT perform clinical-grade filtering.

Note: This module is the single entry point for data transformation.
All downstream modules (features, quality, focus) receive uV data.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, filtfilt, iirnotch

from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    EEGWindow,
    PreprocessedWindow,
)


def preprocess_window(
    window: EEGWindow,
    notch_freq: float = 50.0,
    notch_q: float = 30.0,
    bandpass_low: float = 1.0,
    bandpass_high: float = 45.0,
    bandpass_order: int = 4,
) -> PreprocessedWindow:
    """Preprocess a single EEG window.

    Steps:
        1. Conditional unit conversion (counts → uV)
        2. NaN/Inf cleanup (replace with 0)
        3. Per-channel demean
        4. Notch filter (configurable 50/60 Hz)
        5. Bandpass filter (1-45 Hz, 4th order Butterworth)

    Args:
        window: Input EEG window, unit may be "counts" or "uv".
        notch_freq: Notch center frequency in Hz (default 50.0).
        notch_q: Notch quality factor (default 30.0).
        bandpass_low: Bandpass lower cutoff in Hz (default 1.0).
        bandpass_high: Bandpass upper cutoff in Hz (default 45.0).
        bandpass_order: Butterworth filter order (default 4).

    Returns:
        PreprocessedWindow with unit="uv", demeaned and filtered.
    """
    notes: list[str] = []
    data = window.data.copy().astype(np.float64)

    # Step 1: Conditional unit conversion
    if window.unit == "counts":
        scale = window.vref / window.gain / ((1 << 23) - 1) * 1e6  # µV per count
        data *= scale
        notes.append(f"converted_counts_to_uv(scale={scale:.6e})")
    elif window.unit == "uv":
        pass  # Already in uV
    else:
        raise ValueError(f"Unknown unit: {window.unit!r}, expected 'counts' or 'uv'")

    # Step 2: NaN/Inf cleanup
    nan_mask = ~np.isfinite(data)
    nan_count = int(np.sum(nan_mask))
    if nan_count > 0:
        data[nan_mask] = 0.0
        notes.append(f"replaced {nan_count} NaN/Inf values with 0")

    # Step 3: Per-channel demean
    data -= data.mean(axis=1, keepdims=True)

    # Step 4 & 5: Filtering (with graceful degradation for short data)
    n_channels, n_samples = data.shape
    min_filter_len = max(3 * bandpass_order, 15)

    if n_samples >= min_filter_len:
        try:
            # Notch filter
            b_notch, a_notch = iirnotch(notch_freq, notch_q, window.sample_rate)
            for ch in range(n_channels):
                data[ch] = filtfilt(b_notch, a_notch, data[ch])
            notes.append(f"notch_filter(freq={notch_freq}Hz, q={notch_q})")

            # Bandpass filter
            nyq = window.sample_rate / 2.0
            b_bp, a_bp = butter(
                bandpass_order,
                [bandpass_low / nyq, bandpass_high / nyq],
                btype="band",
            )
            for ch in range(n_channels):
                data[ch] = filtfilt(b_bp, a_bp, data[ch])
            notes.append(
                f"bandpass(order={bandpass_order}, low={bandpass_low}Hz, high={bandpass_high}Hz)"
            )
        except Exception as e:
            notes.append(f"filter_failed({type(e).__name__}: {e}), data demeaned only")
    else:
        notes.append(
            f"filter_skipped(data_too_short: {n_samples} < {min_filter_len}), data demeaned only"
        )

    return PreprocessedWindow(
        raw=window,
        data=data,
        unit="uv",
        sample_rate=window.sample_rate,
        notes=notes,
    )
