"""LSL stream reader for real-time EEG acquisition.

Connects to an LSL stream (typically earEEG_EEG from upper_machine.lsl_proxy)
and pulls EEG chunks. This module depends on pylsl.

Note: This module only reads from LSL — no filtering, no focus estimation.
The output EEGChunk should be fed into lsl_buffer.EEGRollingBuffer.
"""

from __future__ import annotations

import logging

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import EEGChunk

logger = logging.getLogger(__name__)

try:
    import pylsl
except ImportError:
    pylsl = None  # type: ignore[assignment]


class LSLStreamReader:
    """Read EEG data from an LSL stream.

    Args:
        stream_name: LSL stream name to search for (default "earEEG_EEG").
        stream_type: LSL stream type (default "EEG").
        expected_channels: Expected number of EEG channels (default 16).
        unit: Data unit label (default "counts").
    """

    def __init__(
        self,
        stream_name: str = "earEEG_EEG",
        stream_type: str = "EEG",
        expected_channels: int = 16,
        unit: str = "counts",
    ) -> None:
        if pylsl is None:
            raise ImportError(
                "pylsl is required for LSLStreamReader. "
                "Install it with: pip install pylsl"
            )
        self._stream_name = stream_name
        self._stream_type = stream_type
        self._expected_channels = expected_channels
        self._unit = unit
        self._inlet: pylsl.StreamInlet | None = None
        self._sample_rate: float | None = None

    def connect(self, timeout: float = 5.0) -> None:
        """Find and connect to the LSL stream.

        Args:
            timeout: Timeout in seconds for stream discovery.

        Raises:
            RuntimeError: If no matching stream is found.
        """
        logger.info(
            "Searching for LSL stream: %s (type=%s)",
            self._stream_name,
            self._stream_type,
        )

        streams = pylsl.resolve_byprop(
            "name", self._stream_name, timeout=timeout
        )

        if not streams:
            raise RuntimeError(
                f"LSL stream '{self._stream_name}' not found within {timeout}s. "
                "Is upper_machine.lsl_proxy running with --lsl?"
            )

        info = streams[0]
        self._inlet = pylsl.StreamInlet(info)
        self._sample_rate = info.nominal_srate()

        n_channels = info.channel_count()
        if n_channels != self._expected_channels:
            logger.warning(
                "Expected %d channels, got %d",
                self._expected_channels,
                n_channels,
            )

        logger.info(
            "Connected to LSL stream '%s': %.0f Hz, %d channels",
            self._stream_name,
            self._sample_rate,
            n_channels,
        )

    def pull_chunk(
        self, max_samples: int = 128, timeout: float = 0.0
    ) -> EEGChunk | None:
        """Pull a chunk of EEG data from the LSL stream.

        Args:
            max_samples: Maximum number of samples to pull.
            timeout: Timeout in seconds (0.0 = non-blocking).

        Returns:
            EEGChunk if data is available, None otherwise.

        Raises:
            RuntimeError: If not connected.
        """
        if self._inlet is None:
            raise RuntimeError("Not connected. Call connect() first.")

        chunk, timestamps = self._inlet.pull_chunk(
            timeout=timeout, max_samples=max_samples
        )

        if not chunk or len(chunk) == 0:
            return None

        data = np.array(chunk, dtype=np.float64)
        ts = np.array(timestamps, dtype=np.float64)

        return EEGChunk(
            data=data,
            timestamps=ts,
            sample_rate=self._sample_rate or 250.0,
            unit=self._unit,
        )

    @property
    def is_connected(self) -> bool:
        """Whether the inlet is connected."""
        return self._inlet is not None

    @property
    def sample_rate(self) -> float | None:
        """Nominal sample rate of the connected stream."""
        return self._sample_rate
