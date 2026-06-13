"""Tests for features module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.features import (
    BANDS,
    compute_band_power,
    extract_features,
)
from ear_eeg_sound_lab.src.realtime_engine.schemas import PreprocessedWindow, EEGWindow


def _make_preprocessed(data: np.ndarray, sample_rate: float = 250.0) -> PreprocessedWindow:
    """Helper to create a PreprocessedWindow."""
    raw = EEGWindow(
        data=data, sample_rate=sample_rate,
        start_sample=0, start_time=0.0, unit="uv",
    )
    return PreprocessedWindow(raw=raw, data=data, unit="uv", sample_rate=sample_rate)


class TestComputeBandPower(unittest.TestCase):
    """Test compute_band_power function."""

    def test_10hz_sine_dominates_alpha(self):
        """10 Hz sine -> alpha band power should be largest."""
        sample_rate = 250.0
        n_samples = 1000
        t = np.arange(n_samples) / sample_rate
        sine = np.sin(2 * np.pi * 10.0 * t)
        data = np.tile(sine, (4, 1))

        alpha_power = compute_band_power(data, sample_rate, 8.0, 13.0)
        beta_power = compute_band_power(data, sample_rate, 13.0, 30.0)
        delta_power = compute_band_power(data, sample_rate, 1.0, 4.0)

        for ch in range(4):
            self.assertGreater(alpha_power[ch], beta_power[ch])
            self.assertGreater(alpha_power[ch], delta_power[ch])

    def test_20hz_sine_dominates_beta(self):
        """20 Hz sine -> beta band power should be largest."""
        sample_rate = 250.0
        n_samples = 1000
        t = np.arange(n_samples) / sample_rate
        sine = np.sin(2 * np.pi * 20.0 * t)
        data = np.tile(sine, (4, 1))

        beta_power = compute_band_power(data, sample_rate, 13.0, 30.0)
        alpha_power = compute_band_power(data, sample_rate, 8.0, 13.0)

        for ch in range(4):
            self.assertGreater(beta_power[ch], alpha_power[ch])

    def test_output_shape(self):
        """Output should have shape (channels,)."""
        data = np.random.randn(8, 500)
        result = compute_band_power(data, 250.0, 8.0, 13.0)
        self.assertEqual(result.shape, (8,))

    def test_zero_input_no_nan(self):
        """All-zero input should not produce NaN."""
        data = np.zeros((4, 500))
        result = compute_band_power(data, 250.0, 1.0, 45.0)
        self.assertTrue(np.all(np.isfinite(result)))


class TestExtractFeatures(unittest.TestCase):
    """Test extract_features function."""

    def test_mixed_sine_no_nan(self):
        """Mixed sine waves should produce finite output."""
        sample_rate = 250.0
        n_samples = 1000
        t = np.arange(n_samples) / sample_rate
        data = (
            np.sin(2 * np.pi * 5.0 * t) * 10
            + np.sin(2 * np.pi * 10.0 * t) * 20
            + np.sin(2 * np.pi * 20.0 * t) * 15
        )
        data = np.tile(data, (4, 1))
        window = _make_preprocessed(data, sample_rate)

        result = extract_features(window)

        self.assertTrue(np.isfinite(result.theta_beta_ratio))
        self.assertTrue(np.isfinite(result.alpha_beta_ratio))
        self.assertTrue(np.isfinite(result.artifact_ratio))

    def test_theta_beta_ratio_no_divide_by_zero(self):
        """When beta is zero, theta_beta_ratio should be finite."""
        sample_rate = 250.0
        n_samples = 1000
        t = np.arange(n_samples) / sample_rate
        data = np.sin(2 * np.pi * 6.0 * t)
        data = np.tile(data, (4, 1))
        window = _make_preprocessed(data, sample_rate)

        result = extract_features(window)

        self.assertTrue(np.isfinite(result.theta_beta_ratio))

    def test_band_powers_per_channel(self):
        """band_powers should have entries for all channels."""
        data = np.random.randn(8, 500)
        window = _make_preprocessed(data, 250.0)

        result = extract_features(window)

        for ch in range(8):
            self.assertIn(ch, result.band_powers)
            bp = result.band_powers[ch]
            self.assertTrue(hasattr(bp, "delta"))
            self.assertTrue(hasattr(bp, "theta"))
            self.assertTrue(hasattr(bp, "alpha"))
            self.assertTrue(hasattr(bp, "beta"))
            self.assertTrue(hasattr(bp, "gamma"))

    def test_global_band_powers_are_means(self):
        """global_band_powers should be the mean of per-channel powers."""
        data = np.random.randn(4, 500)
        window = _make_preprocessed(data, 250.0)

        result = extract_features(window)

        deltas = [result.band_powers[ch].delta for ch in range(4)]
        self.assertAlmostEqual(
            result.global_band_powers.delta, np.mean(deltas), places=10
        )

    def test_artifact_ratio_range(self):
        """artifact_ratio should be in [0, 1]."""
        data = np.random.randn(4, 500) * 50
        window = _make_preprocessed(data, 250.0)

        result = extract_features(window)

        self.assertGreaterEqual(result.artifact_ratio, 0.0)
        self.assertLessEqual(result.artifact_ratio, 1.0)


if __name__ == "__main__":
    unittest.main()
