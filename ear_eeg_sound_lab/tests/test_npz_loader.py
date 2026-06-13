"""Tests for npz_loader module."""

import unittest
from pathlib import Path

import numpy as np

from ear_eeg_sound_lab.src.integrations.npz_loader import load_npz_session


class TestLoadNPZSession(unittest.TestCase):
    """Test load_npz_session with real and synthetic NPZ files."""

    REAL_NPZ = Path("recordings/20260606_113353.npz")

    def test_load_real_npz(self):
        """读取真实 NPZ 文件, 验证基本结构."""
        if not self.REAL_NPZ.exists():
            self.skipTest(f"Real NPZ not found: {self.REAL_NPZ}")

        session = load_npz_session(self.REAL_NPZ)

        # EEG 必须是 2D (channels, samples)
        self.assertEqual(session.eeg.ndim, 2)
        self.assertEqual(session.eeg.shape[0], 16)  # 16 通道

        # 采样率必须存在且合理
        self.assertGreater(session.eeg_sample_rate, 0)
        self.assertEqual(session.eeg_sample_rate, 250.0)

        # path 应该是 Path 对象
        self.assertIsInstance(session.path, Path)

    def test_load_real_npz_mic_squeezed(self):
        """真实 NPZ 的 MIC (M,1) 应 squeeze 为 (M,)."""
        if not self.REAL_NPZ.exists():
            self.skipTest(f"Real NPZ not found: {self.REAL_NPZ}")

        session = load_npz_session(self.REAL_NPZ)

        if session.mic is not None:
            self.assertEqual(session.mic.ndim, 1, "MIC should be squeezed to 1D")

    def test_load_synthetic_npz(self):
        """读取合成 NPZ, 验证数据完整性."""
        import tempfile
        import os

        eeg = np.random.randn(16, 2500).astype(np.float32)
        mic = np.random.randn(40000).astype(np.float32)

        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
            np.savez(
                f.name,
                eeg=eeg,
                mic=mic,
                eeg_sample_rate=np.int32(250),
                mic_sample_rate=np.int32(16000),
                eeg_channels=np.int32(16),
                mic_channels=np.int32(1),
            )
            tmp_path = f.name

        try:
            session = load_npz_session(tmp_path)

            np.testing.assert_array_equal(session.eeg, eeg)
            self.assertEqual(session.eeg_sample_rate, 250.0)
            self.assertIsNotNone(session.mic)
            np.testing.assert_array_equal(session.mic, mic)
        finally:
            os.unlink(tmp_path)

    def test_missing_optional_fields(self):
        """缺少可选字段时不崩溃."""
        import tempfile
        import os

        eeg = np.random.randn(8, 1000).astype(np.float32)

        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
            np.savez(f.name, eeg=eeg)
            tmp_path = f.name

        try:
            session = load_npz_session(tmp_path)

            self.assertEqual(session.eeg.ndim, 2)
            self.assertIsNone(session.mic)
            self.assertIsNone(session.stimuli)
            # 应有默认采样率
            self.assertGreater(session.eeg_sample_rate, 0)
        finally:
            os.unlink(tmp_path)

    def test_mic_squeeze_2d(self):
        """MIC shape (M,1) 应 squeeze 为 (M,)."""
        import tempfile
        import os

        eeg = np.random.randn(8, 1000).astype(np.float32)
        mic = np.random.randn(5000, 1).astype(np.float32)

        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
            np.savez(f.name, eeg=eeg, mic=mic, eeg_sample_rate=np.int32(250))
            tmp_path = f.name

        try:
            session = load_npz_session(tmp_path)

            self.assertIsNotNone(session.mic)
            self.assertEqual(session.mic.ndim, 1)
            self.assertEqual(session.mic.shape[0], 5000)
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
