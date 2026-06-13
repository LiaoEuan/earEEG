"""Tests for state_provider module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    BandPower,
    EEGWindow,
    EngineOutput,
    FeatureFrame,
    FocusEstimate,
    PreprocessedWindow,
    SignalQuality,
)
from ear_eeg_sound_lab.src.web_app.state_provider import DashboardStateProvider


def _make_engine_output(
    focus_score: int = 70,
    focus_state: str = "focused",
    quality_score: float = 0.9,
    n_channels: int = 16,
    n_samples: int = 500,
) -> EngineOutput:
    """Helper to create a synthetic EngineOutput."""
    data = np.random.randn(n_channels, n_samples)
    window = EEGWindow(
        data=data, sample_rate=250.0,
        start_sample=0, start_time=0.0, unit="uv",
    )
    preprocessed = PreprocessedWindow(raw=window, data=data)
    features = FeatureFrame(
        timestamp=0.0,
        global_band_powers=BandPower(delta=10, theta=8, alpha=15, beta=20, gamma=3),
        theta_beta_ratio=0.4,
        alpha_beta_ratio=0.75,
        artifact_ratio=0.05,
    )
    quality = SignalQuality(score=quality_score, bad_channels=[], warnings=[])
    focus = FocusEstimate(score=focus_score, quality=quality_score, state=focus_state, reasons=["beta_present"])
    return EngineOutput(window=window, preprocessed=preprocessed, features=features, quality=quality, focus=focus)


class TestDashboardStateProvider(unittest.TestCase):

    def test_initial_state(self):
        provider = DashboardStateProvider(channels=16)
        state = provider.get_state()
        self.assertEqual(state["focus"]["score"], 0)
        self.assertEqual(state["device"]["connected"], False)

    def test_update_focus(self):
        provider = DashboardStateProvider(channels=16)
        output = _make_engine_output(focus_score=85, focus_state="focused")
        provider.update(output)
        state = provider.get_state()
        self.assertEqual(state["focus"]["score"], 85)
        self.assertEqual(state["focus"]["state"], "focused")

    def test_update_quality(self):
        provider = DashboardStateProvider(channels=16)
        output = _make_engine_output(quality_score=0.75)
        provider.update(output)
        state = provider.get_state()
        self.assertAlmostEqual(state["focus"]["quality"], 0.75)

    def test_update_band_powers(self):
        provider = DashboardStateProvider(channels=16)
        output = _make_engine_output()
        provider.update(output)
        state = provider.get_state()
        bp = state["features"]["globalBandPowers"]
        self.assertIn("delta", bp)
        self.assertIn("theta", bp)
        self.assertIn("alpha", bp)
        self.assertIn("beta", bp)
        self.assertIn("gamma", bp)

    def test_waveform_rolling(self):
        provider = DashboardStateProvider(channels=4, waveform_seconds=1.0)
        for i in range(5):
            output = _make_engine_output(n_channels=4, n_samples=500)
            provider.update(output)
        state = provider.get_state()
        eeg = state["eeg"]
        self.assertLessEqual(len(eeg["samples"][0]), 250 + 500)

    def test_device_status(self):
        provider = DashboardStateProvider(channels=16)
        provider.set_device_status(connected=True, stream_name="earEEG_EEG", sample_rate=250.0, channels=16)
        state = provider.get_state()
        self.assertEqual(state["device"]["connected"], True)
        self.assertEqual(state["device"]["streamName"], "earEEG_EEG")

    def test_timestamp_present(self):
        provider = DashboardStateProvider(channels=16)
        output = _make_engine_output()
        provider.update(output)
        state = provider.get_state()
        self.assertIn("timestamp", state)
        self.assertIsInstance(state["timestamp"], float)

    def test_state_schema(self):
        """验证 get_state() 返回的完整 schema 结构。"""
        provider = DashboardStateProvider(channels=4, sample_rate=250.0)
        output = _make_engine_output(n_channels=4)
        provider.update(output)

        state = provider.get_state()

        self.assertEqual(set(state.keys()), {"timestamp", "device", "focus", "features", "eeg", "recording"})
        self.assertEqual(
            set(state["device"].keys()),
            {"connected", "streamName", "sampleRate", "channels"},
        )
        self.assertEqual(
            set(state["focus"].keys()),
            {"score", "quality", "state", "reasons"},
        )
        self.assertEqual(
            set(state["features"].keys()),
            {"globalBandPowers", "thetaBetaRatio", "alphaBetaRatio", "artifactRatio"},
        )
        self.assertEqual(
            set(state["features"]["globalBandPowers"].keys()),
            {"delta", "theta", "alpha", "beta", "gamma"},
        )
        self.assertEqual(
            set(state["eeg"].keys()),
            {"channels", "sampleRate", "samples", "timestamps"},
        )


if __name__ == "__main__":
    unittest.main()
