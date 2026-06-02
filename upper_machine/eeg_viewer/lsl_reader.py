"""Background LSL reader for the 16-channel EEG stream."""

from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np

from .eeg_buffer import EEGBuffer

try:
    from pylsl import StreamInlet, resolve_bypred
except ImportError:
    StreamInlet = None
    resolve_bypred = None


class LSLReader:
    def __init__(self, buffer: EEGBuffer, stream_name: str = "earEEG_EEG"):
        self.buffer = buffer
        self.stream_name = stream_name
        self.connected = False
        self.last_error = ""
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._inlet: Optional[StreamInlet] = None

    def start(self) -> None:
        if StreamInlet is None:
            self.last_error = "pylsl is not installed"
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._inlet:
            self._inlet.close_stream()

    def _run(self) -> None:
        while self._running:
            if not self._connect():
                time.sleep(1.0)
                continue

            try:
                while self._running and self._inlet:
                    chunk, _ = self._inlet.pull_chunk(timeout=0.5, max_samples=128)
                    if chunk:
                        samples = np.asarray(chunk, dtype=np.float32)
                        if samples.ndim != 2 or samples.shape[1] != self.buffer.channels:
                            raise RuntimeError(
                                f"stream has {samples.shape[1]} channels; "
                                f"expected {self.buffer.channels}"
                            )
                        self.buffer.append(samples)
            except Exception as exc:
                self.last_error = str(exc)
                self.connected = False
                if self._inlet:
                    self._inlet.close_stream()
                self._inlet = None

    def _connect(self) -> bool:
        try:
            streams = resolve_bypred(f"name='{self.stream_name}'", timeout=1.0)
            if not streams:
                self.last_error = f"waiting for LSL stream '{self.stream_name}'"
                return False
            if streams[0].channel_count() != self.buffer.channels:
                self.last_error = (
                    f"stream has {streams[0].channel_count()} channels; "
                    f"expected {self.buffer.channels}"
                )
                return False
            self._inlet = StreamInlet(streams[0])
            self.connected = True
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self.connected = False
            return False
