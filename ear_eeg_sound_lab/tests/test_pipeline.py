"""Tests for pipeline module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.pipeline import (
    process_eeg_array,
    process_window,
)
from ear_eeg_sound_lab.src.realtime_engine.schemas import EEGWindow


class TestProcessWindow(unittest.TestCase):
    """Test process_window function."""

    def test_basic_processing(self):
        """A normal window should produce valid EngineOutput."""
        sample_rate = 250.0
        n_samples = 500
        t = np.arange(n_samples) / sample_rate
        data = np.sin(2 * np.pi * 10.0 * t) * 20.0
        data = np.tile(data, (8, 1))

        window = EEGWindow(
            data=data.astype(np.float64),
            sample_rate=sample_rate,
            start_sample=0,
            start_time=0.0,
            unit="uv",
        )

        result = process_window(window)

        self.assertIsNotNone(result.window)
        self.assertIsNotNone(result.preprocessed)
        self.assertIsNotNone(result.features)
        self.assertIsNotNone(result.quality)
        self.assertIsNotNone(result.focus)

        self.assertGreaterEqual(result.focus.score, 0)
        self.assertLessEqual(result.focus.score, 100)

        self.assertGreaterEqual(result.quality.score, 0.0)
        self.assertLessEqual(result.quality.score, 1.0)

    def test_no_nan_in_output(self):
        """No NaN should appear anywhere in the output."""
        sample_rate = 250.0
        data = np.random.randn(8, 500) * 50.0
        window = EEGWindow(
            data=data, sample_rate=sample_rate,
            start_sample=0, start_time=0.0, unit="uv",
        )

        result = process_window(window)

        self.assertTrue(np.isfinite(result.features.theta_beta_ratio))
        self.assertTrue(np.isfinite(result.features.alpha_beta_ratio))
        self.assertTrue(np.isfinite(result.features.artifact_ratio))
        self.assertTrue(0 <= result.focus.score <= 100)


class TestProcessEEGArray(unittest.TestCase):
    """Test process_eeg_array function."""

    def test_10_second_eeg(self):
        """10 seconds of EEG should produce multiple outputs."""
        sample_rate = 250.0
        n_samples = 2500
        t = np.arange(n_samples) / sample_rate
        data = np.sin(2 * np.pi * 10.0 * t) * 20.0
        data = np.tile(data, (8, 1))

        outputs = process_eeg_array(data, sample_rate, unit="uv")

        self.assertGreater(len(outputs), 1)

        for out in outputs:
            self.assertGreaterEqual(out.focus.score, 0)
            self.assertLessEqual(out.focus.score, 100)

    def test_counts_unit_input(self):
        """Input with unit='counts' should work end-to-end."""
        sample_rate = 250.0
        n_samples = 2500
        data = np.random.randn(8, n_samples) * 10000.0

        outputs = process_eeg_array(data, sample_rate, unit="counts")

        self.assertGreater(len(outputs), 0)
        for out in outputs:
            self.assertEqual(out.preprocessed.unit, "uv")

    def test_insufficient_data(self):
        """Data shorter than one window → empty output."""
        sample_rate = 250.0
        data = np.random.randn(8, 100)

        outputs = process_eeg_array(data, sample_rate, unit="uv")

        self.assertEqual(len(outputs), 0)

    def test_no_nan_across_windows(self):
        """No NaN should appear in any window's output."""
        sample_rate = 250.0
        data = np.random.randn(8, 2500) * 50.0

        outputs = process_eeg_array(data, sample_rate, unit="uv")

        for out in outputs:
            self.assertTrue(np.isfinite(out.features.theta_beta_ratio))
            self.assertTrue(np.isfinite(out.features.alpha_beta_ratio))


if __name__ == "__main__":
    unittest.main()
