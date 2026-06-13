"""EEG signal quality assessment.

Detects flatline, high amplitude, high peak-to-peak, and noisy channels.
Returns a quality score in [0.0, 1.0] and a list of bad channel indices.

Input: PreprocessedWindow (data in uV)
Output: SignalQuality

Thresholds are configurable via QualityThresholds dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    PreprocessedWindow,
    SignalQuality,
)


@dataclass
class QualityThresholds:
    """Thresholds for signal quality detection.

    Attributes:
        min_std: Minimum standard deviation for non-flatline (uV).
        max_abs_uv: Maximum absolute amplitude (uV).
        max_ptp_uv: Maximum peak-to-peak amplitude (uV).
        noisy_std: Standard deviation above which channel is considered noisy (uV).
    """
    min_std: float = 1e-6
    max_abs_uv: float = 100000.0
    max_ptp_uv: float = 200000.0
    noisy_std: float = 500.0


def estimate_signal_quality(
    window: PreprocessedWindow,
    thresholds: QualityThresholds | None = None,
) -> SignalQuality:
    """Estimate signal quality of a preprocessed EEG window.

    Args:
        window: Preprocessed EEG window, data in uV, shape (channels, samples).
        thresholds: Quality thresholds. Uses defaults if None.

    Returns:
        SignalQuality with score in [0.0, 1.0], bad channel indices, and warnings.
    """
    if thresholds is None:
        thresholds = QualityThresholds()

    data = window.data
    n_channels, _ = data.shape
    bad_channels: list[int] = []
    warnings: list[str] = []

    for ch in range(n_channels):
        ch_data = data[ch]
        ch_std = float(np.std(ch_data))
        ch_max_abs = float(np.max(np.abs(ch_data)))
        ch_ptp = float(np.ptp(ch_data))

        # Flatline detection
        if ch_std < thresholds.min_std:
            bad_channels.append(ch)
            warnings.append(f"channel_{ch}_flatline")
            continue

        # High amplitude detection
        if ch_max_abs > thresholds.max_abs_uv:
            bad_channels.append(ch)
            warnings.append(f"channel_{ch}_high_amplitude")
            continue

        # High peak-to-peak detection
        if ch_ptp > thresholds.max_ptp_uv:
            bad_channels.append(ch)
            warnings.append(f"channel_{ch}_high_ptp")
            continue

        # Noisy detection
        if ch_std > thresholds.noisy_std:
            bad_channels.append(ch)
            warnings.append(f"channel_{ch}_noisy")

    # Quality score: penalize bad channels
    artifact_penalty = min(len(bad_channels) * 0.15, 0.6)
    score = float(np.clip(1.0 - artifact_penalty, 0.0, 1.0))

    return SignalQuality(
        score=score,
        bad_channels=bad_channels,
        warnings=warnings,
    )
