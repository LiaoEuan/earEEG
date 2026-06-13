"""EEG feature extraction — FFT-based band power computation.

Computes delta, theta, alpha, beta, gamma band power using Hann-windowed FFT.
Also computes theta/beta ratio, alpha/beta ratio, and artifact ratio.

Input: PreprocessedWindow (data in uV, shape (channels, samples))
Output: FeatureFrame with per-channel and global band powers.

Note: Band power units are uV^2. Absolute values are less important than ratios.
"""

from __future__ import annotations

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    BandPower,
    FeatureFrame,
    PreprocessedWindow,
)

# EEG frequency band definitions (Hz)
BANDS: dict[str, tuple[float, float]] = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}

# Small constant to prevent division by zero
_EPSILON = 1e-12


def compute_band_power(
    data: np.ndarray,
    sample_rate: float,
    low_hz: float,
    high_hz: float,
) -> np.ndarray:
    """Compute average power in a frequency band using Hann-windowed FFT.

    Args:
        data: EEG data, shape (channels, samples).
        sample_rate: Sampling rate in Hz.
        low_hz: Lower frequency bound in Hz.
        high_hz: Upper frequency bound in Hz.

    Returns:
        Band power per channel, shape (channels,). Units: uV^2.
    """
    n_channels, n_samples = data.shape

    # Apply Hann window to reduce spectral leakage
    hann = np.hanning(n_samples)
    windowed = data * hann[np.newaxis, :]

    # Compute one-sided FFT
    spectrum = np.fft.rfft(windowed, axis=1)
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sample_rate)

    # Power spectrum (|X|^2 / N)
    power = np.abs(spectrum) ** 2 / n_samples

    # Select frequency bins within [low_hz, high_hz]
    mask = (freqs >= low_hz) & (freqs <= high_hz)

    # Average power in the band
    band_power = np.mean(power[:, mask], axis=1)

    return band_power


def extract_features(window: PreprocessedWindow) -> FeatureFrame:
    """Extract all frequency band features from a preprocessed window.

    Args:
        window: Preprocessed EEG window, data in uV, shape (channels, samples).

    Returns:
        FeatureFrame with per-channel band powers, global band powers,
        theta/beta ratio, alpha/beta ratio, and artifact ratio.
    """
    data = window.data
    n_channels = data.shape[0]
    sample_rate = window.sample_rate

    # Compute per-channel band powers
    band_powers: dict[int, BandPower] = {}
    for ch in range(n_channels):
        ch_data = data[ch : ch + 1, :]  # shape (1, samples)
        bp = BandPower(
            delta=float(compute_band_power(ch_data, sample_rate, *BANDS["delta"])[0]),
            theta=float(compute_band_power(ch_data, sample_rate, *BANDS["theta"])[0]),
            alpha=float(compute_band_power(ch_data, sample_rate, *BANDS["alpha"])[0]),
            beta=float(compute_band_power(ch_data, sample_rate, *BANDS["beta"])[0]),
            gamma=float(compute_band_power(ch_data, sample_rate, *BANDS["gamma"])[0]),
        )
        band_powers[ch] = bp

    # Global band powers = mean of per-channel powers
    global_bp = BandPower(
        delta=float(np.mean([bp.delta for bp in band_powers.values()])),
        theta=float(np.mean([bp.theta for bp in band_powers.values()])),
        alpha=float(np.mean([bp.alpha for bp in band_powers.values()])),
        beta=float(np.mean([bp.beta for bp in band_powers.values()])),
        gamma=float(np.mean([bp.gamma for bp in band_powers.values()])),
    )

    # Ratios (with divide-by-zero protection)
    theta_beta_ratio = global_bp.theta / max(global_bp.beta, _EPSILON)
    alpha_beta_ratio = global_bp.alpha / max(global_bp.beta, _EPSILON)

    # Artifact ratio: gamma power as fraction of total power
    total_power = (
        global_bp.delta
        + global_bp.theta
        + global_bp.alpha
        + global_bp.beta
        + global_bp.gamma
    )
    artifact_ratio = global_bp.gamma / max(total_power, _EPSILON)
    artifact_ratio = float(np.clip(artifact_ratio, 0.0, 1.0))

    # Timestamp: center of window
    timestamp = None
    if window.raw.start_time is not None:
        n_samples = data.shape[1]
        timestamp = window.raw.start_time + n_samples / (2.0 * sample_rate)

    return FeatureFrame(
        timestamp=timestamp,
        band_powers=band_powers,
        global_band_powers=global_bp,
        theta_beta_ratio=float(theta_beta_ratio),
        alpha_beta_ratio=float(alpha_beta_ratio),
        artifact_ratio=float(artifact_ratio),
    )
