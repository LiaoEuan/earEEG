"""NPZ session recording for viewer-driven EEG, MIC, and stimuli data."""

from __future__ import annotations

import re
import threading
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from upper_machine.lsl_proxy.audio_player import _to_stereo_16bit


EEG_SAMPLE_RATE = 250
MIC_SAMPLE_RATE = 16000
STIMULI_SAMPLE_RATE = 44100
STIMULI_CHANNELS = 2


class RecordingService:
    def __init__(self, output_dir: str | Path = "recordings"):
        self._output_dir = Path(output_dir)
        self._lock = threading.RLock()
        self._running = False
        self._session_id = ""
        self._start_monotonic = 0.0
        self._stop_monotonic = 0.0
        self._eeg_chunks: list[np.ndarray] = []
        self._mic_chunks: list[np.ndarray] = []
        self._stimuli = _StimulusTimeline()
        self._last_path = ""
        self._last_error = ""

    def start(self, tag: str = "") -> dict:
        with self._lock:
            if self._running:
                return {"ok": False, "error": "recording is already running"}
            now = datetime.now(timezone.utc)
            clean_tag = _safe_tag(tag)
            self._session_id = now.strftime("%Y%m%d_%H%M%S")
            if clean_tag:
                self._session_id = f"{self._session_id}_{clean_tag}"
            self._start_monotonic = time.monotonic()
            self._stop_monotonic = 0.0
            self._eeg_chunks = []
            self._mic_chunks = []
            self._stimuli = _StimulusTimeline()
            self._last_path = ""
            self._last_error = ""
            self._running = True
            return {"ok": True, "status": self.status()}

    def stop(self) -> dict:
        with self._lock:
            if not self._running:
                return {"ok": False, "error": "recording is not running"}
            self._stop_monotonic = time.monotonic()
            self._stimuli.stop(self._stop_monotonic)
            try:
                path = self._save_locked()
                self._last_path = str(path)
            except Exception as exc:
                self._last_error = str(exc)
                self._running = False
                return {"ok": False, "error": str(exc), "status": self.status()}
            self._running = False
            return {"ok": True, "path": self._last_path, "status": self.status()}

    def status(self) -> dict:
        with self._lock:
            elapsed = ((time.monotonic() - self._start_monotonic)
                       if self._running and self._start_monotonic else 0.0)
            eeg_samples = sum(len(chunk) for chunk in self._eeg_chunks)
            mic_samples = sum(len(chunk) for chunk in self._mic_chunks)
            return {
                "running": self._running,
                "sessionId": self._session_id,
                "elapsedSeconds": elapsed,
                "eegSamples": eeg_samples,
                "micSamples": mic_samples,
                "lastPath": self._last_path,
                "lastError": self._last_error,
            }

    def append_eeg(self, samples: np.ndarray) -> None:
        self._append(samples, self._eeg_chunks, expected_channels=16)

    def append_mic(self, samples: np.ndarray) -> None:
        self._append(samples, self._mic_chunks, expected_channels=1)

    def stimulus_play(self, wav_path: str) -> None:
        with self._lock:
            if not self._running:
                return
            try:
                self._stimuli.play(wav_path, time.monotonic())
                self._last_error = ""
            except Exception as exc:
                self._last_error = str(exc)

    def stimulus_pause(self) -> None:
        with self._lock:
            if self._running:
                self._stimuli.pause(time.monotonic())

    def stimulus_resume(self) -> None:
        with self._lock:
            if self._running:
                self._stimuli.resume(time.monotonic())

    def stimulus_stop(self) -> None:
        with self._lock:
            if self._running:
                self._stimuli.stop(time.monotonic())

    def _append(self, samples: np.ndarray, chunks: list[np.ndarray],
                expected_channels: int) -> None:
        values = np.asarray(samples, dtype=np.float32)
        if values.ndim != 2 or values.shape[1] != expected_channels:
            return
        with self._lock:
            if self._running:
                chunks.append(values.copy())

    def _save_locked(self) -> Path:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        path = self._output_dir / f"{self._session_id}.npz"
        eeg_rows = (np.vstack(self._eeg_chunks).astype(np.float32)
                    if self._eeg_chunks else np.zeros((0, 16), dtype=np.float32))
        mic = (np.vstack(self._mic_chunks).astype(np.float32)
               if self._mic_chunks else np.zeros((0, 1), dtype=np.float32))
        eeg = eeg_rows.T
        duration = max(0.0, self._stop_monotonic - self._start_monotonic)
        stimuli = self._stimuli.render(self._start_monotonic, duration)

        np.savez_compressed(
            path,
            eeg=eeg,
            mic=mic,
            stimuli=stimuli,
            eeg_sample_rate=np.array(EEG_SAMPLE_RATE, dtype=np.int32),
            mic_sample_rate=np.array(MIC_SAMPLE_RATE, dtype=np.int32),
            stimuli_sample_rate=np.array(STIMULI_SAMPLE_RATE, dtype=np.int32),
            eeg_channels=np.array(16, dtype=np.int32),
            mic_channels=np.array(1, dtype=np.int32),
            stimuli_channels=np.array(STIMULI_CHANNELS, dtype=np.int32),
        )
        return path


class _StimulusTimeline:
    def __init__(self):
        self._samples = np.zeros((0, STIMULI_CHANNELS), dtype=np.float32)
        self._play_position = 0
        self._play_start: float | None = None
        self._segments: list[tuple[float, np.ndarray, int, int]] = []

    def play(self, wav_path: str, now: float) -> None:
        self.stop(now)
        self._samples = _load_stimulus(wav_path)
        self._play_position = 0
        self._play_start = now

    def pause(self, now: float) -> None:
        self._close_segment(now)
        self._play_start = None

    def resume(self, now: float) -> None:
        if len(self._samples) and self._play_start is None:
            self._play_start = now

    def stop(self, now: float) -> None:
        self._close_segment(now)
        self._play_start = None
        self._play_position = 0

    def render(self, record_start: float, duration: float) -> np.ndarray:
        total = max(0, int(round(duration * STIMULI_SAMPLE_RATE)))
        out = np.zeros((total, STIMULI_CHANNELS), dtype=np.float32)
        for start_time, samples, source_start, source_end in self._segments:
            target_start = int(round((start_time - record_start) * STIMULI_SAMPLE_RATE))
            if target_start < 0:
                source_start -= target_start
                target_start = 0
            if target_start >= total or source_start >= source_end:
                continue
            count = min(source_end - source_start, total - target_start)
            out[target_start:target_start + count] = samples[source_start:source_start + count]
        return out

    def _close_segment(self, now: float) -> None:
        if self._play_start is None or not len(self._samples):
            return
        elapsed = max(0.0, now - self._play_start)
        count = int(round(elapsed * STIMULI_SAMPLE_RATE))
        source_end = min(len(self._samples), self._play_position + count)
        if source_end > self._play_position:
            self._segments.append((self._play_start, self._samples, self._play_position, source_end))
        self._play_position = source_end


def _load_stimulus(wav_path: str) -> np.ndarray:
    with wave.open(wav_path, "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        if sample_rate != STIMULI_SAMPLE_RATE:
            raise ValueError(f"stimulus WAV must be {STIMULI_SAMPLE_RATE}Hz")
        raw = wf.readframes(wf.getnframes())
    pcm = _to_stereo_16bit(raw, channels, sample_width)
    return np.frombuffer(pcm, dtype="<i2").reshape(-1, STIMULI_CHANNELS).astype(np.float32)


def _safe_tag(tag: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", tag.strip())
