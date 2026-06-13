"""Simple NPZ recording service for the web app.

Records EEG data from the pipeline and saves as NPZ.
Thread-safe: append() from processing thread, start/stop from HTTP thread.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


class RecordingService:
    """Records EEG data and saves as NPZ.

    Args:
        output_dir: Directory to save recordings.
    """

    def __init__(self, output_dir: str | Path = "recordings") -> None:
        self._output_dir = Path(output_dir)
        self._lock = threading.Lock()
        self._running = False
        self._session_id = ""
        self._start_monotonic = 0.0
        self._eeg_chunks: list[np.ndarray] = []
        self._last_path = ""
        self._sample_rate = 250.0

    def start(self, sample_rate: float = 250.0, tag: str = "") -> dict:
        """Start a new recording session."""
        with self._lock:
            if self._running:
                return {"ok": False, "error": "already recording"}
            now = datetime.now(timezone.utc)
            self._session_id = now.strftime("%Y%m%d_%H%M%S")
            clean_tag = re.sub(r"[^A-Za-z0-9._-]+", "_", tag.strip())
            if clean_tag:
                self._session_id = f"{self._session_id}_{clean_tag}"
            self._start_monotonic = time.monotonic()
            self._eeg_chunks = []
            self._sample_rate = sample_rate
            self._last_path = ""
            self._running = True
            return {"ok": True, "status": self.status()}

    def stop(self) -> dict:
        """Stop recording and save NPZ."""
        with self._lock:
            if not self._running:
                return {"ok": False, "error": "not recording"}
            try:
                path = self._save()
                self._last_path = str(path)
            except Exception as exc:
                self._running = False
                return {"ok": False, "error": str(exc)}
            self._running = False
            return {"ok": True, "path": self._last_path, "status": self.status()}

    def append_eeg(self, data: np.ndarray) -> None:
        """Append EEG data (channels, samples) to recording."""
        with self._lock:
            if self._running:
                # Store as (samples, channels) for vstack
                self._eeg_chunks.append(data.T.copy())

    def status(self) -> dict:
        """Get current recording status."""
        with self._lock:
            elapsed = (time.monotonic() - self._start_monotonic) if self._running else 0.0
            eeg_samples = sum(c.shape[0] for c in self._eeg_chunks)
            return {
                "running": self._running,
                "sessionId": self._session_id,
                "elapsedSeconds": round(elapsed, 1),
                "eegSamples": eeg_samples,
                "lastPath": self._last_path,
            }

    def list_recordings(self) -> list[dict]:
        """List all NPZ files in the output directory."""
        if not self._output_dir.exists():
            return []
        result = []
        for f in sorted(self._output_dir.glob("*.npz"), reverse=True):
            result.append({
                "name": f.name,
                "path": str(f),
                "sizeBytes": f.stat().st_size,
            })
        return result

    def _save(self) -> Path:
        """Save recorded data as NPZ (must hold lock)."""
        self._output_dir.mkdir(parents=True, exist_ok=True)
        path = self._output_dir / f"{self._session_id}.npz"

        if self._eeg_chunks:
            eeg_rows = np.vstack(self._eeg_chunks).astype(np.float32)
            eeg = eeg_rows.T  # (channels, samples)
        else:
            eeg = np.zeros((16, 0), dtype=np.float32)

        np.savez_compressed(
            path,
            eeg=eeg,
            eeg_sample_rate=np.array(int(self._sample_rate), dtype=np.int32),
            eeg_channels=np.array(eeg.shape[0], dtype=np.int32),
        )
        return path
