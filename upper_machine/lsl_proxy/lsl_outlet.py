"""
LSL outlet manager for earEEG data streams.

Creates and manages 3 StreamOutlets:
  earEEG_EEG    — 16 channels float32  @ 250 Hz
  earEEG_Audio  —  1 channel  float32  @ 16000 Hz
  earEEG_IMU    — 10 channels float32  @ 250 Hz

Timestamp mapping: ESP32 µs timestamps are mapped to LSL time
using the offset between PC clock and ESP32 clock at the first frame.
"""

from typing import Optional

import numpy as np

try:
    from pylsl import StreamInfo, StreamOutlet, local_clock
    HAS_PYLSL = True
except ImportError:
    HAS_PYLSL = False
    StreamInfo = None
    StreamOutlet = None


# ── IMU channel mapping (§5.1) ──────────────────────────────────

IMU_CHANNELS = [
    "quat_w", "quat_x", "quat_y", "quat_z",
    "gyro_x", "gyro_y", "gyro_z",
    "accel_x", "accel_y", "accel_z",
]


class LSLOutletManager:
    """Manages 3 LSL outlets for earEEG data."""

    def __init__(self):
        if not HAS_PYLSL:
            raise RuntimeError("pylsl not installed; cannot create LSL outlets")

        self._outlet_eeg: Optional[StreamOutlet] = None
        self._outlet_audio: Optional[StreamOutlet] = None
        self._outlet_imu: Optional[StreamOutlet] = None

        # Timestamp offset: T_pc = T_esp_offset + T_esp / 1e6
        self._esp_offset: Optional[float] = None

        self._create_outlets()

    # ── outlet creation ─────────────────────────────────────────

    def _create_outlets(self):
        # EEG
        info_eeg = StreamInfo("earEEG_EEG", "EEG",
                              16, 250.0, "float32",
                              source_id="earEEG_esp32")
        info_eeg.desc().append_child_value("manufacturer", "earEEG")
        self._outlet_eeg = StreamOutlet(info_eeg, max_buffered=60)

        # Audio
        info_audio = StreamInfo("earEEG_Audio", "Audio",
                                1, 16000.0, "float32",
                                source_id="earEEG_esp32_mic")
        info_audio.desc().append_child_value("manufacturer", "earEEG")
        self._outlet_audio = StreamOutlet(info_audio, max_buffered=360)

        # IMU
        info_imu = StreamInfo("earEEG_IMU", "IMU",
                              len(IMU_CHANNELS), 250.0, "float32",
                              source_id="earEEG_esp32_imu")
        info_imu.desc().append_child_value("manufacturer", "earEEG")
        ch = info_imu.desc().append_child("channels")
        for name in IMU_CHANNELS:
            ch.append_child("channel") \
             .append_child_value("label", name)
        self._outlet_imu = StreamOutlet(info_imu, max_buffered=60)

        print("[LSL] 3 outlets created: EEG(16ch@250Hz) Audio(1ch@16kHz) IMU(10ch@250Hz)")

    # ── timestamp mapping ───────────────────────────────────────

    def set_origin(self, esp_ts_us: int):
        """Record offset: PC now minus ESP32 timestamp."""
        self._esp_offset = local_clock() - esp_ts_us / 1e6

    def _to_lsl_time(self, esp_ts_us: int) -> float:
        """Map ESP32 µs timestamp to LSL time (seconds)."""
        if self._esp_offset is None:
            return pylsl_wall_time()
        return self._esp_offset + esp_ts_us / 1e6

    # ── push methods ────────────────────────────────────────────

    def push_eeg(self, eeg_raw: bytes, active_channels: int, esp_ts_us: int):
        """
        Parse up to 16ch × 3B raw EEG data and push as float32 sample.
        Zero-pads inactive channels.
        """
        if self._outlet_eeg is None:
            return

        sample = np.zeros(16, dtype=np.float32)
        for ch in range(min(active_channels, 16)):
            off = ch * 3
            raw24 = int.from_bytes(eeg_raw[off:off + 3], byteorder='big', signed=True)
            sample[ch] = float(raw24)  # raw ADC value; optionally scale to µV later

        lsl_ts = self._to_lsl_time(esp_ts_us)
        self._outlet_eeg.push_sample(sample.tolist(), lsl_ts)

    def push_audio(self, mic_samples: bytes, esp_ts_us: int):
        """
        Push 64 mono PCM samples as a chunk to the Audio outlet.
        Each sample is timestamped with linearly interpolated LSL time.
        """
        if self._outlet_audio is None:
            return

        n = min(len(mic_samples) // 2, 64)
        if n == 0:
            return

        chunk = np.zeros(n, dtype=np.float32)
        for i in range(n):
            val = int.from_bytes(mic_samples[i * 2:(i + 1) * 2],
                                 byteorder='little', signed=True)
            chunk[i] = float(val)

        base_ts = self._to_lsl_time(esp_ts_us)
        # Each sample is 1/16000 s apart
        ts_step = 1.0 / 16000.0
        timestamps = np.array([base_ts + i * ts_step for i in range(n)])

        self._outlet_audio.push_chunk(chunk.tolist(), timestamps)

    def push_imu(self, quat_w: float, quat_x: float, quat_y: float, quat_z: float,
                 esp_ts_us: int):
        """Push 10-channel IMU sample (quaternion + reserved zeros)."""
        if self._outlet_imu is None:
            return

        sample = [quat_w, quat_x, quat_y, quat_z,
                  0.0, 0.0, 0.0,   # gyro (not populated from current ESP32 frame yet)
                  0.0, 0.0, 0.0]   # accel (not populated from current ESP32 frame yet)

        lsl_ts = self._to_lsl_time(esp_ts_us)
        self._outlet_imu.push_sample(sample, lsl_ts)

    # ── cleanup ─────────────────────────────────────────────────

    def close(self):
        for out in [self._outlet_eeg, self._outlet_audio, self._outlet_imu]:
            if out is not None:
                out.__del__()


def pylsl_wall_time() -> float:
    """Return the current LSL clock value."""
    return local_clock()
