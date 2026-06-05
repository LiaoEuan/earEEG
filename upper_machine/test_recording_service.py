import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from upper_machine.eeg_viewer import recording_service
from upper_machine.eeg_viewer.recording_service import RecordingService


class RecordingServiceTest(unittest.TestCase):
    def test_stop_writes_npz_with_expected_arrays(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = RecordingService(tmpdir)
            self.assertTrue(service.start("subject 01")["ok"])
            service.append_eeg(np.arange(250 * 16, dtype=np.float32).reshape(250, 16))
            service.append_mic(np.arange(16000, dtype=np.float32).reshape(16000, 1))

            result = service.stop()

            self.assertTrue(result["ok"])
            path = Path(result["path"])
            self.assertTrue(path.exists())
            with np.load(path) as data:
                self.assertEqual(data["eeg"].shape, (16, 250))
                self.assertEqual(data["mic"].shape, (16000, 1))
                self.assertEqual(data["stimuli"].shape[1], 2)
                self.assertEqual(int(data["eeg_sample_rate"]), 250)
                self.assertEqual(int(data["mic_sample_rate"]), 16000)
                self.assertEqual(int(data["stimuli_sample_rate"]), 44100)
                np.testing.assert_array_equal(data["eeg"][:, 0], np.arange(16, dtype=np.float32))

    def test_stimulus_timeline_renders_played_wav_segment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "tone.wav"
            frames = np.arange(200, dtype="<i2").reshape(100, 2)
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(recording_service.STIMULI_SAMPLE_RATE)
                wf.writeframes(frames.tobytes())

            timeline = recording_service._StimulusTimeline()
            timeline.play(str(wav_path), now=10.0)
            timeline.pause(now=10.001)
            rendered = timeline.render(record_start=10.0, duration=0.003)

            played = int(round(0.001 * recording_service.STIMULI_SAMPLE_RATE))
            self.assertEqual(rendered.shape, (132, 2))
            np.testing.assert_array_equal(rendered[:played], frames[:played].astype(np.float32))
            self.assertTrue(np.all(rendered[played:] == 0.0))


if __name__ == "__main__":
    unittest.main()
