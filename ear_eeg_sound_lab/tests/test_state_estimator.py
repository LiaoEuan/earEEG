"""Tests for state_estimator module."""

import unittest
import numpy as np
from ear_eeg_sound_lab.src.realtime_engine.schemas import BandPower, FeatureFrame, FocusEstimate, SignalQuality
from ear_eeg_sound_lab.src.realtime_engine.state_estimator import StateEstimate, estimate_state


def _make_features(theta=5.0, beta=5.0, alpha=5.0, delta=3.0, gamma=2.0, artifact=0.1):
    global_bp = BandPower(delta=delta, theta=theta, alpha=alpha, beta=beta, gamma=gamma)
    return FeatureFrame(
        timestamp=0.0, band_powers={}, global_band_powers=global_bp,
        theta_beta_ratio=theta / max(beta, 1e-12),
        alpha_beta_ratio=alpha / max(beta, 1e-12),
        artifact_ratio=artifact,
    )

def _make_quality(score=0.9):
    return SignalQuality(score=score, bad_channels=[], warnings=[])

def _make_focus(score=70, state="focused"):
    return FocusEstimate(score=score, quality=0.9, state=state, reasons=["beta_present"])


class TestStateEstimator(unittest.TestCase):

    def test_output_range(self):
        features = _make_features()
        quality = _make_quality()
        focus = _make_focus()
        state = estimate_state(features, quality, focus)
        for attr in ["focus", "alertness", "relaxation", "fatigue", "affect_arousal", "affect_valence_hint"]:
            val = getattr(state, attr)
            self.assertGreaterEqual(val, 0, f"{attr} < 0")
            self.assertLessEqual(val, 100, f"{attr} > 100")

    def test_low_quality_low_confidence(self):
        features = _make_features()
        state_low = estimate_state(features, _make_quality(0.2), _make_focus())
        state_high = estimate_state(features, _make_quality(0.9), _make_focus())
        self.assertLess(state_low.confidence, state_high.confidence)

    def test_high_theta_beta_increases_fatigue(self):
        state_high = estimate_state(_make_features(theta=15.0, beta=3.0), _make_quality(), _make_focus())
        state_low = estimate_state(_make_features(theta=3.0, beta=15.0), _make_quality(), _make_focus())
        self.assertGreater(state_high.fatigue, state_low.fatigue)

    def test_high_alpha_increases_relaxation(self):
        state_high = estimate_state(_make_features(alpha=20.0, beta=3.0), _make_quality(), _make_focus())
        state_low = estimate_state(_make_features(alpha=3.0, beta=20.0), _make_quality(), _make_focus())
        self.assertGreater(state_high.relaxation, state_low.relaxation)

    def test_affect_experimental_warning(self):
        state = estimate_state(_make_features(), _make_quality(), _make_focus())
        self.assertTrue(state.experimental.get("affect"))
        self.assertIn("experimental", state.experimental.get("warning", "").lower())

    def test_labels_not_empty(self):
        state = estimate_state(_make_features(), _make_quality(), _make_focus())
        self.assertGreater(len(state.labels), 0)


if __name__ == "__main__":
    unittest.main()
