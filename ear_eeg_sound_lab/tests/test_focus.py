"""Tests for focus module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.focus import estimate_focus
from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    BandPower,
    FeatureFrame,
    SignalQuality,
)


def _make_quality(score: float = 0.9, bad_channels: list[int] | None = None) -> SignalQuality:
    """Helper to create SignalQuality."""
    return SignalQuality(
        score=score,
        bad_channels=bad_channels or [],
        warnings=[],
    )


def _make_features(
    theta: float = 5.0,
    beta: float = 5.0,
    alpha: float = 5.0,
    artifact_ratio: float = 0.1,
) -> FeatureFrame:
    """Helper to create FeatureFrame with specific global band powers."""
    global_bp = BandPower(
        delta=3.0,
        theta=theta,
        alpha=alpha,
        beta=beta,
        gamma=2.0,
    )
    theta_beta = theta / max(beta, 1e-12)
    alpha_beta = alpha / max(beta, 1e-12)
    return FeatureFrame(
        timestamp=0.0,
        band_powers={},
        global_band_powers=global_bp,
        theta_beta_ratio=theta_beta,
        alpha_beta_ratio=alpha_beta,
        artifact_ratio=artifact_ratio,
    )


class TestEstimateFocus(unittest.TestCase):
    """Test estimate_focus function."""

    def test_low_quality_low_score(self):
        """Quality < 0.4 → score should be ≤ 40, state='noisy'."""
        quality = _make_quality(score=0.3)
        features = _make_features()

        result = estimate_focus(features, quality)

        self.assertLessEqual(result.score, 40)
        self.assertEqual(result.state, "noisy")
        self.assertIn("poor_signal_quality", result.reasons)

    def test_beta_dominant_higher_than_theta(self):
        """Beta-dominant → higher score than theta-dominant."""
        quality = _make_quality(score=0.9)

        beta_dominant = _make_features(theta=3.0, beta=10.0)
        theta_dominant = _make_features(theta=10.0, beta=3.0)

        result_beta = estimate_focus(beta_dominant, quality)
        result_theta = estimate_focus(theta_dominant, quality)

        self.assertGreater(result_beta.score, result_theta.score)

    def test_score_range(self):
        """Score must always be in [0, 100]."""
        quality = _make_quality(score=0.9)

        for _ in range(50):
            theta = np.random.uniform(0.1, 50.0)
            beta = np.random.uniform(0.1, 50.0)
            alpha = np.random.uniform(0.1, 50.0)
            artifact = np.random.uniform(0.0, 1.0)
            features = _make_features(theta=theta, beta=beta, alpha=alpha, artifact_ratio=artifact)

            result = estimate_focus(features, quality)

            self.assertGreaterEqual(result.score, 0)
            self.assertLessEqual(result.score, 100)

    def test_reasons_not_empty(self):
        """Reasons should never be empty."""
        quality = _make_quality(score=0.9)
        features = _make_features()

        result = estimate_focus(features, quality)

        self.assertGreater(len(result.reasons), 0)

    def test_state_labels(self):
        """State should be one of the defined labels."""
        quality = _make_quality(score=0.9)
        features = _make_features()

        result = estimate_focus(features, quality)

        valid_states = {"focused", "stable", "relaxed", "fatigued", "noisy"}
        self.assertIn(result.state, valid_states)

    def test_quality_weighting(self):
        """Higher quality → higher score (all else equal)."""
        features = _make_features(theta=3.0, beta=10.0)

        high_q = estimate_focus(features, _make_quality(score=0.95))
        low_q = estimate_focus(features, _make_quality(score=0.5))

        self.assertGreater(high_q.score, low_q.score)

    def test_artifact_penalty(self):
        """High artifact_ratio → lower score."""
        quality = _make_quality(score=0.9)

        low_artifact = _make_features(artifact_ratio=0.1)
        high_artifact = _make_features(artifact_ratio=0.5)

        result_low = estimate_focus(low_artifact, quality)
        result_high = estimate_focus(high_artifact, quality)

        self.assertGreater(result_low.score, result_high.score)


if __name__ == "__main__":
    unittest.main()
