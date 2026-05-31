"""
LSL inlet module — subscribes to earEEG streams from lsl_proxy.

Subscribed streams:
  earEEG_EEG    — 24 channels float32  @ 250 Hz
  earEEG_Audio  —  1 channel  float32  @ 16000 Hz
  earEEG_IMU    — 11 channels float32  @ 250 Hz
"""

import time
from typing import Optional, NamedTuple
from collections import deque

import numpy as np

try:
    from pylsl import StreamInlet, resolve_bypred
    HAS_PYLSL = True
except ImportError:
    HAS_PYLSL = False
    StreamInlet = None


class InletConfig(NamedTuple):
    name: str
    channel_count: int

STREAMS = [
    InletConfig("earEEG_EEG", 24),
    InletConfig("earEEG_Audio", 1),
    InletConfig("earEEG_IMU", 11),
]


class LSLInletManager:
    def __init__(self, timeout: float = 5.0):
        if not HAS_PYLSL:
            raise RuntimeError("pylsl not installed")

        self._inlets: dict[str, StreamInlet] = {}
        self._buffers: dict[str, list] = {}
        self._timestamps: dict[str, list] = {}
        self._sample_counts: dict[str, int] = {}

        deadline = time.time() + timeout
        for cfg in STREAMS:
            print(f"[inlet] resolving {cfg.name} ...")
            streams = resolve_bypred(f"name='{cfg.name}'", timeout=timeout)
            if not streams:
                remaining = deadline - time.time()
                if remaining > 0:
                    streams = resolve_bypred(f"name='{cfg.name}'", timeout=remaining)
            if not streams:
                raise RuntimeError(f"stream '{cfg.name}' not found on LSL network")

            inlet = StreamInlet(streams[0])
            self._inlets[cfg.name] = inlet
            self._buffers[cfg.name] = []
            self._timestamps[cfg.name] = []
            self._sample_counts[cfg.name] = 0
            print(f"[inlet] {cfg.name} connected ({cfg.channel_count}ch, "
                  f"{streams[0].nominal_srate():.0f} Hz)")

    def pull_all(self, max_chunk: int = 360) -> dict[str, np.ndarray]:
        result = {}
        for name, inlet in self._inlets.items():
            chunk, ts = inlet.pull_chunk(timeout=0.0, max_samples=max_chunk)
            if chunk:
                self._buffers[name].append(np.array(chunk, dtype=np.float32))
                self._timestamps[name].append(np.array(ts, dtype=np.float64))
                self._sample_counts[name] += len(chunk)
                result[name] = np.array(chunk, dtype=np.float32)
        return result

    def pull_blocking(self, timeout: float = 1.0) -> dict[str, np.ndarray]:
        result = {}
        for name, inlet in self._inlets.items():
            chunk, ts = inlet.pull_chunk(timeout=timeout, max_samples=360)
            if chunk:
                self._buffers[name].append(np.array(chunk, dtype=np.float32))
                self._timestamps[name].append(np.array(ts, dtype=np.float64))
                self._sample_counts[name] += len(chunk)
                result[name] = np.array(chunk, dtype=np.float32)
        return result

    def flush_buffers(self) -> dict[str, Optional[np.ndarray]]:
        result = {}
        for name in self._inlets:
            if self._buffers[name]:
                data = np.vstack(self._buffers[name])
                self._buffers[name].clear()
            else:
                data = None
            if self._timestamps[name]:
                ts = np.hstack(self._timestamps[name])
                self._timestamps[name].clear()
            else:
                ts = np.array([], dtype=np.float64)
            result[name] = data
        return result

    def sample_count(self, name: str) -> int:
        return self._sample_counts.get(name, 0)

    def close(self):
        for inlet in self._inlets.values():
            inlet.close_stream()
