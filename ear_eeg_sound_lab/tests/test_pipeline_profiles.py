"""Tests for pipeline behavior with different EEG profiles.

These tests verify that the algorithm can distinguish between
different EEG patterns (focused, relaxed, fatigued, noisy).
"""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.pipeline import process_eeg_array
from ear_eeg_sound_lab.src.realtime_engine.preprocessing import preprocess_window
from ear_eeg_sound_lab.src.realtime_engine.schemas import EEGWindow


def _make_eeg_window(data: np.ndarray, sample_rate: float = 250.0) -> EEGWindow:
    """Create a PreprocessedWindow-ready EEGWindow in uV."""
    return EEGWindow(
        data=data.astype(np.float64),
        sample_rate=sample_rate,
        start_sample=0,
        start_time=0.0,
        unit="uv",
    )


class TestPipelineProfiles(unittest.TestCase):
    """Test that pipeline produces distinct outputs for different EEG patterns."""

    def _run_profile(self, data: np.ndarray, sample_rate: float = 250.0):
        """Run pipeline on data array and return list of (focus, quality)."""
        outputs = process_eeg_array(data, sample_rate, unit="uv")
        return [(o.focus.score, o.focus.state, o.quality.score) for o in outputs]

    def test_beta_dominant_focused(self):
        """Beta-dominant pattern (20Hz) should score higher than theta-dominant."""
        sr = 250.0
        n = 2500  # 10s
        t = np.arange(n) / sr

        # Beta-dominant: high 20Hz, low 6Hz
        beta_data = np.sin(2 * np.pi * 20.0 * t) * 15.0 + np.sin(2 * np.pi * 6.0 * t) * 3.0
        beta_data = np.tile(beta_data, (8, 1))

        # Theta-dominant: high 6Hz, low 20Hz
        theta_data = np.sin(2 * np.pi * 6.0 * t) * 15.0 + np.sin(2 * np.pi * 20.0 * t) * 3.0
        theta_data = np.tile(theta_data, (8, 1))

        beta_results = self._run_profile(beta_data, sr)
        theta_results = self._run_profile(theta_data, sr)

        beta_scores = [r[0] for r in beta_results]
        theta_scores = [r[0] for r in theta_results]

        avg_beta = np.mean(beta_scores)
        avg_theta = np.mean(theta_scores)

        self.assertGreater(avg_beta, avg_theta,
            f"Beta-dominant ({avg_beta:.1f}) should score higher than theta-dominant ({avg_theta:.1f})")

    def test_noisy_low_quality(self):
        """High-amplitude random noise should produce low quality."""
        sr = 250.0
        n = 2500
        # Random noise with very high amplitude (simulating bad electrode contact)
        np.random.seed(42)
        noisy_data = np.random.randn(8, n) * 5000.0  # Very high amplitude noise

        results = self._run_profile(noisy_data, sr)

        qualities = [r[2] for r in results]
        avg_quality = np.mean(qualities)

        # Quality should be lower than a clean signal
        clean_data = np.sin(2 * np.pi * 10.0 * np.arange(n) / sr) * 10.0
        clean_data = np.tile(clean_data, (8, 1))
        clean_results = self._run_profile(clean_data, sr)
        clean_qualities = [r[2] for r in clean_results]
        avg_clean_quality = np.mean(clean_qualities)

        self.assertLess(avg_quality, avg_clean_quality,
            f"Noisy quality ({avg_quality:.2f}) should be less than clean ({avg_clean_quality:.2f})")

    def test_alpha_dominant_relaxed(self):
        """Alpha-dominant pattern (10Hz) should produce distinct state vs beta-dominant."""
        sr = 250.0
        n = 2500
        t = np.arange(n) / sr

        # Alpha-dominant: high 10Hz
        alpha_data = np.sin(2 * np.pi * 10.0 * t) * 20.0 + np.sin(2 * np.pi * 20.0 * t) * 3.0
        alpha_data = np.tile(alpha_data, (8, 1))

        results = self._run_profile(alpha_data, sr)
        states = [r[1] for r in results]

        # Alpha-dominant should NOT all be "focused"
        # At least some should be "stable", "relaxed", etc.
        focused_ratio = states.count("focused") / len(states)
        self.assertLess(focused_ratio, 0.9,
            f"Alpha-dominant should not be all focused (got {focused_ratio:.0%} focused)")

    def test_flatline_noisy_state(self):
        """Flatline channels should produce noisy/low-quality state."""
        sr = 250.0
        n = 2500
        # Mix of flatline and normal channels
        data = np.zeros((8, n))
        # Only channels 0-3 have signal
        t = np.arange(n) / sr
        for ch in range(4):
            data[ch] = np.sin(2 * np.pi * 10.0 * t) * 10.0
        # Channels 4-7 are flatline (zeros)

        results = self._run_profile(data, sr)

        qualities = [r[2] for r in results]
        avg_quality = np.mean(qualities)

        # Quality should be penalized for flatline channels
        self.assertLess(avg_quality, 0.9,
            f"Half-flatline quality ({avg_quality:.2f}) should be < 0.9")

    def test_score_range_across_profiles(self):
        """All profiles should produce scores in valid range."""
        sr = 250.0
        n = 2500
        t = np.arange(n) / sr

        profiles = {
            "pure_alpha": np.sin(2 * np.pi * 10.0 * t),
            "pure_beta": np.sin(2 * np.pi * 20.0 * t),
            "pure_theta": np.sin(2 * np.pi * 6.0 * t),
            "mixed": np.sin(2 * np.pi * 10.0 * t) + np.sin(2 * np.pi * 20.0 * t),
            "noise": np.random.randn(n) * 50,
        }

        for name, signal in profiles.items():
            data = np.tile(signal, (8, 1))
            results = self._run_profile(data, sr)

            for focus_score, state, quality_score in results:
                self.assertGreaterEqual(focus_score, 0, f"{name}: focus < 0")
                self.assertLessEqual(focus_score, 100, f"{name}: focus > 100")
                self.assertGreaterEqual(quality_score, 0.0, f"{name}: quality < 0")
                self.assertLessEqual(quality_score, 1.0, f"{name}: quality > 1.0")
                self.assertIn(state, {"focused", "stable", "relaxed", "fatigued", "noisy"},
                    f"{name}: invalid state '{state}'")


if __name__ == "__main__":
    unittest.main()
