"""Tests for windowing module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.windowing import iter_eeg_windows


class TestIterEEGWindows(unittest.TestCase):
    """Test iter_eeg_windows behavior."""

    def test_basic_windowing(self):
        """250Hz, 1000 samples, 2s window, 0.5s step -> correct count."""
        sample_rate = 250.0
        n_samples = 1000  # 4 seconds
        n_channels = 16
        eeg = np.random.randn(n_channels, n_samples)

        windows = list(iter_eeg_windows(eeg, sample_rate))

        # 2s = 500 samples, 0.5s = 125 samples
        # starts: 0, 125, 250, 375, 500 -> 5 windows
        self.assertEqual(len(windows), 5)

    def test_window_shape(self):
        """Each window should have shape (channels, window_samples)."""
        sample_rate = 250.0
        n_channels = 8
        eeg = np.random.randn(n_channels, 1000)

        windows = list(iter_eeg_windows(eeg, sample_rate))

        for w in windows:
            self.assertEqual(w.data.shape, (n_channels, 500))

    def test_start_sample_increments(self):
        """start_sample should increment by step_samples."""
        sample_rate = 250.0
        eeg = np.random.randn(4, 2000)

        windows = list(iter_eeg_windows(eeg, sample_rate))

        # step = 0.5s * 250 = 125 samples
        for i in range(len(windows) - 1):
            self.assertEqual(
                windows[i + 1].start_sample - windows[i].start_sample, 125
            )

    def test_start_time(self):
        """start_time should equal start_sample / sample_rate."""
        sample_rate = 250.0
        eeg = np.random.randn(4, 1000)

        windows = list(iter_eeg_windows(eeg, sample_rate))

        for w in windows:
            expected_time = w.start_sample / sample_rate
            self.assertAlmostEqual(w.start_time, expected_time)

    def test_insufficient_data(self):
        """If data < one window, no windows should be returned."""
        sample_rate = 250.0
        eeg = np.random.randn(4, 400)  # 1.6 seconds < 2 seconds

        windows = list(iter_eeg_windows(eeg, sample_rate))

        self.assertEqual(len(windows), 0)

    def test_unit_passthrough(self):
        """Unit should be passed through to EEGWindow."""
        sample_rate = 250.0
        eeg = np.random.randn(4, 1000)

        windows = list(iter_eeg_windows(eeg, sample_rate, unit="uv"))

        for w in windows:
            self.assertEqual(w.unit, "uv")

    def test_custom_window_and_step(self):
        """Custom window_seconds and step_seconds should work."""
        sample_rate = 250.0
        eeg = np.random.randn(4, 2500)  # 10 seconds

        # 1s window, 0.25s step
        windows = list(iter_eeg_windows(eeg, sample_rate, window_seconds=1.0, step_seconds=0.25))

        self.assertGreater(len(windows), 30)
        for w in windows:
            self.assertEqual(w.data.shape[1], 250)

    def test_gain_vref_passthrough(self):
        """gain and vref should be passed through."""
        sample_rate = 250.0
        eeg = np.random.randn(4, 1000)

        windows = list(iter_eeg_windows(eeg, sample_rate, gain=12.0, vref=2.5))

        for w in windows:
            self.assertEqual(w.gain, 12.0)
            self.assertEqual(w.vref, 2.5)


if __name__ == "__main__":
    unittest.main()
