"""EEG rolling buffer for real-time LSL data.

Accumulates LSL chunks into a continuous buffer and provides
fixed-length windows for the processing pipeline.

Internal storage: (channels, samples) format.
Output: EEGWindow objects.

Cursor design uses three global-index values:
  _buffer_start_sample  -- global index of the first sample currently in buffer
  _total_received       -- total samples ever received (monotonic)
  _next_window_start    -- global index of the next window to output
"""

from __future__ import annotations

from collections import deque

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import EEGChunk, EEGWindow


class EEGRollingBuffer:
    """Rolling buffer that accumulates LSL EEG chunks and provides windows.

    Args:
        channels: Number of EEG channels.
        sample_rate: Sampling rate in Hz.
        capacity_seconds: Maximum buffer length in seconds (default 30.0).
        unit: Data unit label (default "counts").
    """

    def __init__(
        self,
        channels: int,
        sample_rate: float,
        capacity_seconds: float = 30.0,
        unit: str = "counts",
    ) -> None:
        self._channels = channels
        self._sample_rate = sample_rate
        self._capacity_samples = int(capacity_seconds * sample_rate)
        self._unit = unit
        self._buffer: deque[np.ndarray] = deque()
        self._buffer_start_sample: int = 0
        self._total_received: int = 0
        self._next_window_start: int = 0

    def append_chunk(self, chunk: EEGChunk) -> None:
        """Append an LSL chunk to the buffer.

        Args:
            chunk: EEGChunk with data shape (samples, channels).
        """
        data_t = chunk.data.T  # (channels, samples)
        self._buffer.append(data_t)
        self._total_received += data_t.shape[1]

        # Evict oldest chunks when over capacity
        while self._buffer:
            current_in_buffer = self._total_received - self._buffer_start_sample
            if current_in_buffer <= self._capacity_samples:
                break
            removed = self._buffer.popleft()
            self._buffer_start_sample += removed.shape[1]

        # Snap next_window_start forward if it fell behind the buffer
        self._next_window_start = max(
            self._next_window_start, self._buffer_start_sample
        )

    def has_window(self, window_seconds: float = 2.0) -> bool:
        """Check if enough data is available for a window."""
        window_samples = int(window_seconds * self._sample_rate)
        current_in_buffer = self._total_received - self._buffer_start_sample
        return self._next_window_start + window_samples <= self._buffer_start_sample + current_in_buffer

    def latest_window(
        self,
        window_seconds: float = 2.0,
        gain: float = 24.0,
        vref: float = 4.5,
    ) -> EEGWindow:
        """Get the latest window of data (non-destructive)."""
        if not self.has_window(window_seconds):
            raise RuntimeError(
                f"Not enough data: need {window_seconds}s, "
                f"have {(self._total_received - self._buffer_start_sample) / self._sample_rate:.1f}s"
            )

        window_samples = int(window_seconds * self._sample_rate)
        all_data = np.concatenate(list(self._buffer), axis=1)
        data = all_data[:, -window_samples:]

        current_in_buffer = self._total_received - self._buffer_start_sample
        global_start = self._buffer_start_sample + current_in_buffer - window_samples

        return EEGWindow(
            data=data.astype(np.float64),
            sample_rate=self._sample_rate,
            start_sample=global_start,
            start_time=global_start / self._sample_rate,
            unit=self._unit,
            gain=gain,
            vref=vref,
        )

    def pop_next_window(
        self,
        window_seconds: float = 2.0,
        step_seconds: float = 0.5,
        gain: float = 24.0,
        vref: float = 4.5,
    ) -> EEGWindow | None:
        """Pop the next window from the buffer (advances pointer)."""
        if not self.has_window(window_seconds):
            return None

        window_samples = int(window_seconds * self._sample_rate)
        step_samples = int(step_seconds * self._sample_rate)

        # Convert global start to relative index within current buffer
        relative_start = self._next_window_start - self._buffer_start_sample
        relative_end = relative_start + window_samples

        all_data = np.concatenate(list(self._buffer), axis=1)

        if relative_end > all_data.shape[1]:
            return None

        data = all_data[:, relative_start:relative_end]
        global_start = self._next_window_start
        self._next_window_start += step_samples

        return EEGWindow(
            data=data.astype(np.float64),
            sample_rate=self._sample_rate,
            start_sample=global_start,
            start_time=global_start / self._sample_rate,
            unit=self._unit,
            gain=gain,
            vref=vref,
        )

    @property
    def total_samples(self) -> int:
        """Total samples currently in the buffer."""
        return self._total_received - self._buffer_start_sample
