import csv
import os
import struct
import time
from datetime import datetime, timezone

import numpy as np


class StorageWriter:
    def __init__(self, output_dir: str, session_tag: str = ""):
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._session_id = f"{ts}_{session_tag}" if session_tag else ts
        self._output_dir = os.path.join(output_dir, self._session_id)
        os.makedirs(self._output_dir, exist_ok=True)

        self._csv_files: dict[str, object] = {}
        self._csv_writers: dict[str, object] = {}
        self._wav_f = None
        self._wav_samples_total = 0
        self._wav_path = ""
        self._wav_sample_rate = 16000

        self._session_start = time.time()
        self._frames_total = {"earEEG_EEG": 0, "earEEG_IMU": 0, "earEEG_Audio": 0}

    @property
    def session_dir(self) -> str:
        return self._output_dir

    @property
    def session_id(self) -> str:
        return self._session_id

    def open_csv(self, stream_name: str, header: list[str]):
        path = os.path.join(self._output_dir, f"{self._session_id}_{stream_name}.csv")
        f = open(path, "w", newline="")
        w = csv.writer(f)
        w.writerow(header)
        self._csv_files[stream_name] = f
        self._csv_writers[stream_name] = w

    def write_csv_row(self, stream_name: str, row: list):
        if stream_name in self._csv_writers:
            self._csv_writers[stream_name].writerow(row)
            self._frames_total[stream_name] += 1

    def open_wav(self, sample_rate: int = 16000, channels: int = 1):
        self._wav_sample_rate = sample_rate
        self._wav_path = os.path.join(self._output_dir, f"{self._session_id}_Audio.wav")
        self._wav_f = open(self._wav_path, "wb")
        self._wav_samples_total = 0

    def write_wav_chunk(self, audio: np.ndarray):
        if self._wav_f is None:
            return
        int16_data = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        self._wav_f.write(int16_data.tobytes())
        self._wav_samples_total += len(int16_data)
        self._frames_total["earEEG_Audio"] += len(int16_data)

    def close_wav(self):
        if self._wav_f is None or self._wav_samples_total == 0:
            if self._wav_f:
                self._wav_f.close()
            return

        data_len = self._wav_samples_total * 2
        riff_size = 36 + data_len
        self._wav_f.seek(0)
        self._wav_f.write(b"RIFF")
        self._wav_f.write(struct.pack("<I", riff_size))
        self._wav_f.write(b"WAVE")
        self._wav_f.write(b"fmt ")
        self._wav_f.write(struct.pack("<I", 16))
        self._wav_f.write(struct.pack("<H", 1))
        self._wav_f.write(struct.pack("<H", 1))
        self._wav_f.write(struct.pack("<I", self._wav_sample_rate))
        self._wav_f.write(struct.pack("<I", self._wav_sample_rate * 2))
        self._wav_f.write(struct.pack("<H", 2))
        self._wav_f.write(struct.pack("<H", 16))
        self._wav_f.write(b"data")
        self._wav_f.write(struct.pack("<I", data_len))
        self._wav_f.close()

    def write_metadata(self):
        elapsed = time.time() - self._session_start
        path = os.path.join(self._output_dir, f"{self._session_id}_metadata.txt")
        with open(path, "w") as f:
            f.write(f"session_id: {self._session_id}\n")
            f.write(f"start_utc: {datetime.now(timezone.utc).isoformat()}\n")
            f.write(f"duration_seconds: {elapsed:.1f}\n")
            for name, count in self._frames_total.items():
                f.write(f"stream_{name}_samples: {count}\n")

    def close(self):
        self.close_wav()
        for f in self._csv_files.values():
            f.close()
        self.write_metadata()
