import struct
import unittest

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


if __name__ == "__main__":
    unittest.main()
