"""Tests for quality module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.quality import (
    QualityThresholds,
    estimate_signal_quality,
)
from ear_eeg_sound_lab.src.realtime_engine.schemas import PreprocessedWindow, EEGWindow


def _make_preprocessed(data: np.ndarray, sample_rate: float = 250.0) -> PreprocessedWindow:
    """Helper to create a PreprocessedWindow."""
    raw = EEGWindow(
        data=data, sample_rate=sample_rate,
        start_sample=0, start_time=0.0, unit="uv",
    )
    return PreprocessedWindow(raw=raw, data=data, unit="uv", sample_rate=sample_rate)


class TestEstimateSignalQuality(unittest.TestCase):
    """Test estimate_signal_quality function."""

    def test_all_zeros_low_quality(self):
        """All-zero data -> flatline -> low quality."""
        data = np.zeros((8, 500))
        window = _make_preprocessed(data)

        result = estimate_signal_quality(window)

        self.assertLess(result.score, 0.5)
        self.assertGreater(len(result.bad_channels), 0)

    def test_normal_sine_high_quality(self):
        """Normal 10 Hz sine, 10 uV -> high quality."""
        sample_rate = 250.0
        n_samples = 500
        t = np.arange(n_samples) / sample_rate
        sine = np.sin(2 * np.pi * 10.0 * t) * 10.0
        data = np.tile(sine, (8, 1))
        window = _make_preprocessed(data, sample_rate)

        result = estimate_signal_quality(window)

        self.assertGreater(result.score, 0.8)
        self.assertEqual(len(result.bad_channels), 0)

    def test_single_channel_high_amplitude(self):
        """One channel with extreme amplitude -> marked as bad."""
        sample_rate = 250.0
        n_samples = 500
        t = np.arange(n_samples) / sample_rate
        data = np.tile(np.sin(2 * np.pi * 10.0 * t) * 10.0, (8, 1))
        data[3, :] = np.sin(2 * np.pi * 10.0 * t) * 200000.0
        window = _make_preprocessed(data, sample_rate)

        result = estimate_signal_quality(window)

        self.assertIn(3, result.bad_channels)
        self.assertLess(result.score, 1.0)

    def test_score_range(self):
        """Score must always be in [0.0, 1.0]."""
        for _ in range(20):
            n_ch = np.random.randint(1, 16)
            data = np.random.randn(n_ch, 500) * np.random.uniform(0.1, 1000)
            window = _make_preprocessed(data)
            result = estimate_signal_quality(window)
            self.assertGreaterEqual(result.score, 0.0)
            self.assertLessEqual(result.score, 1.0)

    def test_custom_thresholds(self):
        """Custom thresholds should be respected."""
        data = np.random.randn(4, 500) * 10.0
        window = _make_preprocessed(data)

        strict = QualityThresholds(min_std=1e6, max_abs_uv=0.001)
        result = estimate_signal_quality(window, thresholds=strict)

        self.assertLess(result.score, 0.5)


if __name__ == "__main__":
    unittest.main()
