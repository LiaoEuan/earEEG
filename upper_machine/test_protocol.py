import struct
import unittest

from upper_machine.common.eeg_units import (
    adc_volts_per_count,
    decode_openbci_24bit_count,
    decode_openbci_eeg_counts,
    decode_openbci_eeg_uv,
    openbci_counts_to_uv,
)
from upper_machine.common.protocol import (
    EEG_DATA_BYTES,
    IMU_PAYLOAD_BYTES,
    MIC_SAMPLES_PER_PACKET,
    FrameParser,
    TYPE_SENSOR,
    build_frame,
    parse_sensor_data,
)


def sensor_payload(mic_count: int = MIC_SAMPLES_PER_PACKET) -> bytes:
    eeg = bytes(range(EEG_DATA_BYTES))
    mic = bytes(mic_count * 2)
    imu = struct.pack("<ffff", 1.0, 0.0, 0.0, 0.0) + bytes(IMU_PAYLOAD_BYTES - 16)
    return struct.pack("<HBB", 7, 8, 0) + eeg + struct.pack("<H", mic_count) + mic + imu


class ProtocolTest(unittest.TestCase):
    def test_sensor_frame_round_trip(self):
        frame = build_frame(TYPE_SENSOR, 123456, sensor_payload())
        parsed = FrameParser().feed(frame)
        self.assertEqual(len(parsed), 1)
        sensor = parse_sensor_data(parsed[0])
        self.assertIsNotNone(sensor)
        self.assertEqual(sensor.seq_id, 7)
        self.assertEqual(sensor.active_channels, 8)
        self.assertEqual(sensor.timestamp, 123456)

    def test_parser_preserves_fragmented_frame(self):
        frame = build_frame(TYPE_SENSOR, 42, sensor_payload())
        parser = FrameParser()
        self.assertEqual(parser.feed(frame[:11]), [])
        self.assertEqual(len(parser.feed(frame[11:])), 1)

    def test_sensor_rejects_unexpected_mic_count(self):
        frame = build_frame(TYPE_SENSOR, 42, sensor_payload(mic_count=63))
        parsed = FrameParser().feed(frame)
        self.assertEqual(len(parsed), 1)
        self.assertIsNone(parse_sensor_data(parsed[0]))

    def test_openbci_signed_24bit_decode(self):
        self.assertEqual(decode_openbci_24bit_count(bytes.fromhex("000001")), 1)
        self.assertEqual(decode_openbci_24bit_count(bytes.fromhex("7fffff")), (1 << 23) - 1)
        self.assertEqual(decode_openbci_24bit_count(bytes.fromhex("800000")), -(1 << 23))
        self.assertEqual(decode_openbci_24bit_count(bytes.fromhex("ffffff")), -1)

    def test_openbci_counts_to_microvolts(self):
        full_scale_uv = openbci_counts_to_uv((1 << 23) - 1, gain=24.0)
        self.assertAlmostEqual(full_scale_uv, 187500.0, places=6)
        self.assertAlmostEqual(adc_volts_per_count(24.0) * 1e6, 0.022351744455, places=12)

    def test_decode_openbci_eeg_uv_uses_active_channels(self):
        raw = bytes.fromhex("000001 ffffff 000002").replace(b" ", b"")
        self.assertEqual(decode_openbci_eeg_counts(raw, 2), [1, -1])
        uv = decode_openbci_eeg_uv(raw, 2, gain=24.0)
        self.assertAlmostEqual(uv[0], -uv[1], places=12)


if __name__ == "__main__":
    unittest.main()
