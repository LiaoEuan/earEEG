"""Background focus computation service for the EEG viewer.

Periodically takes a snapshot from EEGBuffer, runs the realtime engine pipeline,
and stores the latest focus/quality/band powers for the WebSocket handler.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.pipeline import process_window
from ear_eeg_sound_lab.src.realtime_engine.schemas import EEGWindow
from ear_eeg_sound_lab.src.realtime_engine.state_estimator import estimate_state


class FocusService:
    """Background thread that computes focus from EEGBuffer snapshots.

    Args:
        eeg_buffer: The viewer's EEGBuffer instance.
        interval: Computation interval in seconds (default 0.5).
        window_seconds: How much data to process (default 2.0).
        sample_rate: EEG sample rate (default 250).
    """

    def __init__(
        self,
        eeg_buffer,
        interval: float = 0.5,
        window_seconds: float = 2.0,
        sample_rate: float = 250.0,
    ) -> None:
        self._buffer = eeg_buffer
        self._interval = interval
        self._window_seconds = window_seconds
        self._sample_rate = sample_rate
        self._lock = threading.Lock()
        self._latest: dict = {
            "score": 0,
            "quality": 0.0,
            "state": "unknown",
            "reasons": [],
            "bandPowers": {"delta": 0, "theta": 0, "alpha": 0, "beta": 0, "gamma": 0},
            "thetaBetaRatio": 0.0,
            "alphaBetaRatio": 0.0,
        }
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start the background computation thread."""
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def get_focus(self) -> dict:
        """Get the latest focus computation result (thread-safe)."""
        with self._lock:
            return dict(self._latest)

    def _run(self) -> None:
        """Background loop: snapshot -> pipeline -> store result."""
        while not self._stop_event.is_set():
            try:
                self._compute()
            except Exception as e:
                # Log but don't crash the thread
                print(f"[focus] computation error: {e}")
            self._stop_event.wait(self._interval)

    def _compute(self) -> None:
        """Take a snapshot and run the pipeline."""
        # Get latest data from buffer
        # EEGBuffer.snapshot returns (samples, channels) float32
        data, total = self._buffer.snapshot(self._window_seconds)

        if data.shape[0] < self._sample_rate:
            # Not enough data (less than 1 second)
            return

        # Convert to (channels, samples) float64 for pipeline
        eeg_data = data.T.astype(np.float64)

        window = EEGWindow(
            data=eeg_data,
            sample_rate=self._sample_rate,
            start_sample=0,
            start_time=0.0,
            unit="counts",
            gain=24.0,
            vref=4.5,
        )

        output = process_window(window)

        state = estimate_state(output.features, output.quality, output.focus)

        gbp = output.features.global_band_powers
        with self._lock:
            self._latest = {
                "score": output.focus.score,
                "quality": round(output.focus.quality, 2),
                "state": output.focus.state,
                "reasons": output.focus.reasons,
                "bandPowers": {
                    "delta": round(gbp.delta, 2),
                    "theta": round(gbp.theta, 2),
                    "alpha": round(gbp.alpha, 2),
                    "beta": round(gbp.beta, 2),
                    "gamma": round(gbp.gamma, 2),
                },
                "thetaBetaRatio": round(output.features.theta_beta_ratio, 3),
                "alphaBetaRatio": round(output.features.alpha_beta_ratio, 3),
                "stateEstimate": {
                    "focus": state.focus,
                    "alertness": state.alertness,
                    "relaxation": state.relaxation,
                    "fatigue": state.fatigue,
                    "affectArousal": state.affect_arousal,
                    "affectValenceHint": state.affect_valence_hint,
                    "confidence": state.confidence,
                    "labels": state.labels,
                    "experimental": state.experimental,
                },
            }
