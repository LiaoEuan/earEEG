"""Tests for preprocessing module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.preprocessing import preprocess_window
from ear_eeg_sound_lab.src.realtime_engine.schemas import EEGWindow


def _make_window(data: np.ndarray, sample_rate: float = 250.0, unit: str = "counts") -> EEGWindow:
    """Helper to create an EEGWindow from data array."""
    return EEGWindow(
        data=data.astype(np.float64),
        sample_rate=sample_rate,
        start_sample=0,
        start_time=0.0,
        unit=unit,
        gain=24.0,
        vref=4.5,
    )


class TestPreprocessWindow(unittest.TestCase):
    """Test preprocess_window behavior."""

    def test_dc_offset_removal(self):
        """DC offset should be removed — output mean ≈ 0 per channel."""
        n_channels, n_samples = 4, 500
        data = np.ones((n_channels, n_samples)) * 10000.0
        window = _make_window(data, unit="uv")

        result = preprocess_window(window)

        for ch in range(n_channels):
            self.assertAlmostEqual(
                np.mean(result.data[ch]), 0.0, places=5,
                msg=f"Channel {ch} mean should be ~0 after demean"
            )

    def test_nan_cleanup(self):
        """NaN values should be replaced with 0, and noted."""
        n_channels, n_samples = 4, 500
        data = np.random.randn(n_channels, n_samples)
        data[0, 10] = np.nan
        data[2, 20:25] = np.inf
        window = _make_window(data, unit="uv")

        result = preprocess_window(window)

        self.assertTrue(np.all(np.isfinite(result.data)))
        self.assertTrue(any("NaN" in n or "Inf" in n for n in result.notes))

    def test_counts_to_uv_conversion(self):
        """Counts should be converted to uV when unit='counts'."""
        n_channels, n_samples = 4, 500
        data = np.ones((n_channels, n_samples)) * 1000.0
        window = _make_window(data, unit="counts")

        result = preprocess_window(window)

        self.assertEqual(result.unit, "uv")

    def test_uv_passthrough(self):
        """If unit='uv', no counts→uV conversion should occur."""
        n_channels, n_samples = 4, 500
        data = np.random.randn(n_channels, n_samples) * 10.0
        window = _make_window(data, unit="uv")

        result = preprocess_window(window)

        self.assertEqual(result.unit, "uv")
        self.assertTrue(np.all(np.isfinite(result.data)))

    def test_output_is_float64(self):
        """Output data should be float64."""
        data = np.random.randn(4, 500).astype(np.float32)
        window = _make_window(data, unit="uv")

        result = preprocess_window(window)

        self.assertEqual(result.data.dtype, np.float64)

    def test_notes_populated(self):
        """PreprocessedWindow.notes should contain processing info."""
        data = np.random.randn(4, 500)
        window = _make_window(data, unit="uv")

        result = preprocess_window(window)

        self.assertIsInstance(result.notes, list)

    def test_filter_does_not_crash_short_data(self):
        """Very short data should not crash (graceful degradation)."""
        data = np.random.randn(4, 10)
        window = _make_window(data, unit="uv")

        result = preprocess_window(window)
        self.assertTrue(np.all(np.isfinite(result.data)))

    def test_sine_wave_survives_filtering(self):
        """A 10 Hz sine wave should survive 1-45 Hz bandpass."""
        sample_rate = 250.0
        n_samples = 500
        t = np.arange(n_samples) / sample_rate
        sine = np.sin(2 * np.pi * 10.0 * t) * 50.0
        data = np.tile(sine, (4, 1))
        window = _make_window(data, unit="uv")

        result = preprocess_window(window)

        for ch in range(4):
            self.assertGreater(np.std(result.data[ch]), 1.0)


if __name__ == "__main__":
    unittest.main()
