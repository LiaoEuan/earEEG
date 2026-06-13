"""Tests for lsl_buffer module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.integrations.lsl_buffer import EEGRollingBuffer
from ear_eeg_sound_lab.src.realtime_engine.schemas import EEGChunk


class TestEEGRollingBuffer(unittest.TestCase):
    """Test EEGRollingBuffer behavior."""

    def test_append_and_has_window(self):
        """After enough data, has_window should return True."""
        buffer = EEGRollingBuffer(channels=4, sample_rate=250.0)

        for i in range(5):
            chunk = EEGChunk(
                data=np.random.randn(128, 4),
                timestamps=np.arange(128) / 250.0 + i * 128 / 250.0,
                sample_rate=250.0,
            )
            buffer.append_chunk(chunk)

        self.assertTrue(buffer.has_window())

    def test_not_enough_data(self):
        """Before enough data, has_window should return False."""
        buffer = EEGRollingBuffer(channels=4, sample_rate=250.0)

        chunk = EEGChunk(
            data=np.random.randn(100, 4),
            timestamps=np.arange(100) / 250.0,
            sample_rate=250.0,
        )
        buffer.append_chunk(chunk)

        self.assertFalse(buffer.has_window())

    def test_latest_window_shape(self):
        """latest_window should return (channels, window_samples) shape."""
        buffer = EEGRollingBuffer(channels=8, sample_rate=250.0)

        for i in range(5):
            chunk = EEGChunk(
                data=np.random.randn(128, 8),
                timestamps=np.arange(128) / 250.0 + i * 128 / 250.0,
                sample_rate=250.0,
            )
            buffer.append_chunk(chunk)

        window = buffer.latest_window()
        self.assertEqual(window.data.shape, (8, 500))

    def test_pop_next_window(self):
        """pop_next_window should return a window and advance the pointer."""
        buffer = EEGRollingBuffer(channels=4, sample_rate=250.0)

        for i in range(7):
            chunk = EEGChunk(
                data=np.random.randn(128, 4),
                timestamps=np.arange(128) / 250.0 + i * 128 / 250.0,
                sample_rate=250.0,
            )
            buffer.append_chunk(chunk)

        window = buffer.pop_next_window()
        self.assertIsNotNone(window)
        self.assertEqual(window.data.shape[0], 4)
        self.assertEqual(window.data.shape[1], 500)

    def test_capacity_limit(self):
        """Buffer should not grow beyond capacity."""
        buffer = EEGRollingBuffer(channels=4, sample_rate=250.0, capacity_seconds=5.0)

        for i in range(20):
            chunk = EEGChunk(
                data=np.random.randn(128, 4),
                timestamps=np.arange(128) / 250.0 + i * 128 / 250.0,
                sample_rate=250.0,
            )
            buffer.append_chunk(chunk)

        self.assertLessEqual(buffer.total_samples, 5.0 * 250.0 + 128)


if __name__ == "__main__":
    unittest.main()
