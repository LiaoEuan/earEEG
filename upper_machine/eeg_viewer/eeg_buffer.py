"""Thread-safe rolling buffer for the EEG viewer."""

from __future__ import annotations

import threading

import numpy as np


class EEGBuffer:
    def __init__(self, channels: int = 16, sample_rate: int = 250,
                 capacity_seconds: int = 10):
        self.channels = channels
        self.sample_rate = sample_rate
        self.capacity = sample_rate * capacity_seconds
        self._data = np.zeros((self.capacity, channels), dtype=np.float32)
        self._write_pos = 0
        self._size = 0
        self._total_samples = 0
        self._lock = threading.Lock()

    def append(self, samples: np.ndarray) -> None:
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 2 or samples.shape[1] != self.channels:
            raise ValueError(f"expected samples shaped (n, {self.channels})")
        if len(samples) == 0:
            return
        if len(samples) > self.capacity:
            samples = samples[-self.capacity:]

        with self._lock:
            end = self._write_pos + len(samples)
            split = min(len(samples), self.capacity - self._write_pos)
            self._data[self._write_pos:self._write_pos + split] = samples[:split]
            if split < len(samples):
                self._data[:end % self.capacity] = samples[split:]
            self._write_pos = end % self.capacity
            self._size = min(self.capacity, self._size + len(samples))
            self._total_samples += len(samples)

    def snapshot(self, seconds: float) -> tuple[np.ndarray, int]:
        requested = min(self.capacity, max(1, int(seconds * self.sample_rate)))
        with self._lock:
            count = min(requested, self._size)
            start = (self._write_pos - count) % self.capacity
            if start + count <= self.capacity:
                data = self._data[start:start + count].copy()
            else:
                data = np.vstack((self._data[start:], self._data[:self._write_pos]))
            return data, self._total_samples

    def snapshot_since(self, total_samples: int) -> tuple[np.ndarray, int]:
        with self._lock:
            count = min(max(0, self._total_samples - total_samples), self._size)
            start = (self._write_pos - count) % self.capacity
            if start + count <= self.capacity:
                data = self._data[start:start + count].copy()
            else:
                data = np.vstack((self._data[start:], self._data[:self._write_pos]))
            return data, self._total_samples
