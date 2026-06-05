import unittest
import threading
import time

import numpy as np

from upper_machine.eeg_viewer.eeg_buffer import EEGBuffer
from upper_machine.eeg_viewer.impedance_service import ImpedanceService


class ViewerImpedanceTest(unittest.TestCase):
    def test_collect_channel_uses_fresh_lsl_buffer_samples(self):
        buffer = EEGBuffer(channels=16, sample_rate=250)
        service = ImpedanceService(buffer, "http://127.0.0.1:8787")
        buffer.append(np.zeros((4, 16), dtype=np.float32))
        fresh = np.zeros((8, 16), dtype=np.float32)
        fresh[:, 2] = np.arange(8, dtype=np.float32) + 100

        def append_later():
            time.sleep(0.05)
            buffer.append(fresh)

        threading.Thread(target=append_later, daemon=True).start()

        samples = service._collect_channel(3, 8, timeout=1.0)

        self.assertEqual(samples.tolist(), fresh[:, 2].tolist())


if __name__ == "__main__":
    unittest.main()
