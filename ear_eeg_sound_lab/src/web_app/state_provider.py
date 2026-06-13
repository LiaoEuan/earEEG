"""Dashboard state provider — aggregates EngineOutput into WebSocket-ready state.

Maintains rolling EEG waveform buffer and latest focus/quality/features.
Thread-safe: update() is called from the processing thread,
get_state() is called from the WebSocket handler thread.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import EngineOutput


class DashboardStateProvider:
    """Aggregates pipeline outputs into a single dashboard state dict.

    Args:
        waveform_seconds: How many seconds of EEG waveform to keep.
        channels: Number of EEG channels.
        sample_rate: EEG sampling rate in Hz.
    """

    def __init__(
        self,
        waveform_seconds: float = 2.0,
        channels: int = 16,
        sample_rate: float = 250.0,
    ) -> None:
        self._waveform_samples = int(waveform_seconds * sample_rate)
        self._channels = channels
        self._sample_rate = sample_rate
        self._lock = threading.Lock()

        self._focus: dict = {"score": 0, "quality": 0.0, "state": "unknown", "reasons": []}
        self._features: dict = {
            "globalBandPowers": {"delta": 0, "theta": 0, "alpha": 0, "beta": 0, "gamma": 0},
            "thetaBetaRatio": 0.0,
            "alphaBetaRatio": 0.0,
            "artifactRatio": 0.0,
        }
        self._device: dict = {
            "connected": False,
            "streamName": "",
            "sampleRate": sample_rate,
            "channels": channels,
        }

        self._waveform: np.ndarray = np.zeros((channels, 0))
        self._waveform_timestamps: np.ndarray = np.array([])
        self._last_timestamp: float = 0.0

    def update(self, output: EngineOutput) -> None:
        """Update state with a new pipeline output."""
        with self._lock:
            self._last_timestamp = time.time()

            self._focus = {
                "score": output.focus.score,
                "quality": round(output.focus.quality, 2),
                "state": output.focus.state,
                "reasons": output.focus.reasons,
            }

            gbp = output.features.global_band_powers
            self._features = {
                "globalBandPowers": {
                    "delta": round(gbp.delta, 2),
                    "theta": round(gbp.theta, 2),
                    "alpha": round(gbp.alpha, 2),
                    "beta": round(gbp.beta, 2),
                    "gamma": round(gbp.gamma, 2),
                },
                "thetaBetaRatio": round(output.features.theta_beta_ratio, 3),
                "alphaBetaRatio": round(output.features.alpha_beta_ratio, 3),
                "artifactRatio": round(output.features.artifact_ratio, 3),
            }

            new_data = output.window.data  # (channels, samples)
            self._waveform = np.concatenate([self._waveform, new_data], axis=1)
            if self._waveform.shape[1] > self._waveform_samples:
                self._waveform = self._waveform[:, -self._waveform_samples:]

            if output.window.start_time is not None:
                n_new = new_data.shape[1]
                new_ts = np.arange(n_new) / self._sample_rate + output.window.start_time
                self._waveform_timestamps = np.concatenate([self._waveform_timestamps, new_ts])
                if len(self._waveform_timestamps) > self._waveform_samples:
                    self._waveform_timestamps = self._waveform_timestamps[-self._waveform_samples:]

    def set_device_status(
        self,
        connected: bool,
        stream_name: str = "",
        sample_rate: float = 250.0,
        channels: int = 16,
    ) -> None:
        """Update device connection status."""
        with self._lock:
            self._device = {
                "connected": connected,
                "streamName": stream_name,
                "sampleRate": sample_rate,
                "channels": channels,
            }

    def get_state(self) -> dict:
        """Return the complete dashboard state dict (thread-safe)."""
        with self._lock:
            return {
                "timestamp": self._last_timestamp,
                "device": dict(self._device),
                "focus": dict(self._focus),
                "features": {
                    "globalBandPowers": dict(self._features["globalBandPowers"]),
                    "thetaBetaRatio": self._features["thetaBetaRatio"],
                    "alphaBetaRatio": self._features["alphaBetaRatio"],
                    "artifactRatio": self._features["artifactRatio"],
                },
                "eeg": {
                    "channels": self._channels,
                    "sampleRate": self._sample_rate,
                    "samples": self._waveform.tolist(),
                    "timestamps": self._waveform_timestamps.tolist(),
                },
                "recording": {
                    "running": False,
                    "sessionId": "",
                    "elapsedSeconds": 0,
                    "lastPath": "",
                },
            }
