"""Realtime EEG processing pipeline.

Chains preprocessing → features → quality → focus for each window.
Provides both single-window and array-level processing.

This module does not depend on LSL, HTTP, or UI.
"""

from __future__ import annotations

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.features import extract_features
from ear_eeg_sound_lab.src.realtime_engine.focus import estimate_focus
from ear_eeg_sound_lab.src.realtime_engine.preprocessing import preprocess_window
from ear_eeg_sound_lab.src.realtime_engine.quality import estimate_signal_quality
from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    EEGWindow,
    EngineOutput,
)
from ear_eeg_sound_lab.src.realtime_engine.windowing import iter_eeg_windows


def process_window(window: EEGWindow) -> EngineOutput:
    """Process a single EEG window through the full pipeline.

    Args:
        window: Input EEG window (counts or uV).

    Returns:
        EngineOutput with preprocessed data, features, quality, and focus.
    """
    preprocessed = preprocess_window(window)
    features = extract_features(preprocessed)
    quality = estimate_signal_quality(preprocessed)
    focus = estimate_focus(features, quality)

    return EngineOutput(
        window=window,
        preprocessed=preprocessed,
        features=features,
        quality=quality,
        focus=focus,
    )


def process_eeg_array(
    eeg: np.ndarray,
    sample_rate: float,
    window_seconds: float = 2.0,
    step_seconds: float = 0.5,
    unit: str = "counts",
    gain: float = 24.0,
    vref: float = 4.5,
) -> list[EngineOutput]:
    """Process an entire EEG array through the pipeline (offline entry point).

    Args:
        eeg: Continuous EEG data, shape (channels, samples).
        sample_rate: Sampling rate in Hz.
        window_seconds: Window length in seconds (default 2.0).
        step_seconds: Step size in seconds (default 0.5).
        unit: Data unit, "counts" or "uv".
        gain: ADS1299 gain for counts→uV conversion.
        vref: ADS1299 reference voltage for counts→uV conversion.

    Returns:
        List of EngineOutput, one per window.
    """
    windows = iter_eeg_windows(
        eeg, sample_rate, window_seconds, step_seconds, unit, gain, vref
    )
    return [process_window(w) for w in windows]
