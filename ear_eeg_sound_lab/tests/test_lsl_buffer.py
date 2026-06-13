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

    def test_continuous_output_stability(self):
        """Continuous 30s input should produce stable window output every 0.5s."""
        buffer = EEGRollingBuffer(channels=4, sample_rate=250.0, capacity_seconds=10.0)

        outputs = []
        # Feed 30 seconds of data in 128-sample chunks
        total_chunks = int(30.0 * 250.0 / 128)  # ~58 chunks
        for i in range(total_chunks):
            chunk = EEGChunk(
                data=np.random.randn(128, 4),
                timestamps=np.arange(128) / 250.0 + i * 128 / 250.0,
                sample_rate=250.0,
            )
            buffer.append_chunk(chunk)
            w = buffer.pop_next_window()
            if w is not None:
                outputs.append(w.start_sample)

        # Should have emitted many windows (at least 20 for 30s with 0.5s step)
        self.assertGreater(len(outputs), 20)

        # Each output should advance by step_samples
        for i in range(1, len(outputs)):
            self.assertEqual(outputs[i] - outputs[i - 1], 125)  # 0.5s * 250Hz

    def test_pop_consistent_with_has_window(self):
        """has_window() True must not return None from pop_next_window()."""
        buffer = EEGRollingBuffer(channels=4, sample_rate=250.0, capacity_seconds=10.0)

        for i in range(60):
            chunk = EEGChunk(
                data=np.random.randn(128, 4),
                timestamps=np.arange(128) / 250.0 + i * 128 / 250.0,
                sample_rate=250.0,
            )
            buffer.append_chunk(chunk)

            if buffer.has_window():
                w = buffer.pop_next_window()
                self.assertIsNotNone(
                    w, f"has_window=True but pop returned None at chunk {i}"
                )

    def test_capacity_eviction_continues_output(self):
        """Capacity eviction should not prevent further window output."""
        buffer = EEGRollingBuffer(channels=4, sample_rate=250.0, capacity_seconds=5.0)

        outputs_after_eviction = []
        eviction_started = False

        for i in range(100):
            chunk = EEGChunk(
                data=np.random.randn(128, 4),
                timestamps=np.arange(128) / 250.0 + i * 128 / 250.0,
                sample_rate=250.0,
            )
            buffer.append_chunk(chunk)

            # After ~5 seconds, eviction should start
            if i * 128 / 250.0 > 5.0:
                eviction_started = True

            if eviction_started:
                w = buffer.pop_next_window()
                if w is not None:
                    outputs_after_eviction.append(w)

        self.assertGreater(
            len(outputs_after_eviction),
            10,
            "Should continue producing windows after eviction",
        )


if __name__ == "__main__":
    unittest.main()
