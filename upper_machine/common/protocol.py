"""
Shared protocol module — mirrors earEEG/include/protocol.h and crc16.c.

TCP wire format (§4.2 of design.md):
  [SYNC 2B][TYPE 1B][LEN 2B BE][TIMESTAMP 8B LE][PAYLOAD LEN B][CRC16 2B LE]
"""

import struct
from dataclasses import dataclass
from typing import Optional, Tuple

# ── Frame constants ────────────────────────────────────────────────

SYNC_0 = 0xEE
SYNC_1 = 0x01

TYPE_SENSOR       = 0x01  # ESP32 → PC: composite sensor data
TYPE_DNLINK_AUDIO = 0x02  # PC → ESP32: downlink audio
TYPE_COMMAND      = 0x03  # PC → ESP32: command
TYPE_ACK          = 0x04  # ESP32 → PC: ack

CMD_START_ACQ       = 0x01
CMD_STOP_ACQ        = 0x02
CMD_SET_EEG_PARAMS  = 0x03

PROTO_HEADER_SIZE = 13    # SYNC(2) + TYPE(1) + LEN(2) + TIMESTAMP(8)
PROTO_CRC_SIZE    = 2
PROTO_FRAME_OVERHEAD = PROTO_HEADER_SIZE + PROTO_CRC_SIZE  # 15

# ── Payload sizes (§4.4) ──────────────────────────────────────────

EEG_CHANNELS_MAX      = 24
EEG_BYTES_PER_CHANNEL = 3
EEG_DATA_BYTES        = EEG_CHANNELS_MAX * EEG_BYTES_PER_CHANNEL  # 72
MIC_SAMPLES_PER_PACKET = 64
MIC_PAYLOAD_BYTES     = 2 + MIC_SAMPLES_PER_PACKET * 2  # 130
IMU_PAYLOAD_BYTES     = 38
SENSOR_PAYLOAD_SIZE   = (2 + 2 + EEG_DATA_BYTES + MIC_PAYLOAD_BYTES + IMU_PAYLOAD_BYTES)  # 244

# ── CRC-16-IBM table (poly 0x8005, init 0xFFFF, no final XOR) ────

_CRC16_TABLE = [
    0x0000,0xC0C1,0xC181,0x0140,0xC301,0x03C0,0x0280,0xC241,
    0xC601,0x06C0,0x0780,0xC741,0x0500,0xC5C1,0xC481,0x0440,
    0xCC01,0x0CC0,0x0D80,0xCD41,0x0F00,0xCFC1,0xCE81,0x0E40,
    0x0A00,0xCAC1,0xCB81,0x0B40,0xC901,0x09C0,0x0880,0xC841,
    0xD801,0x18C0,0x1980,0xD941,0x1B00,0xDBC1,0xDA81,0x1A40,
    0x1E00,0xDEC1,0xDF81,0x1F40,0xDD01,0x1DC0,0x1C80,0xDC41,
    0x1400,0xD4C1,0xD581,0x1540,0xD701,0x17C0,0x1680,0xD641,
    0xD201,0x12C0,0x1380,0xD341,0x1100,0xD1C1,0xD081,0x1040,
    0xF001,0x30C0,0x3180,0xF141,0x3300,0xF3C1,0xF281,0x3240,
    0x3600,0xF6C1,0xF781,0x3740,0xF501,0x35C0,0x3480,0xF441,
    0x3C00,0xFCC1,0xFD81,0x3D40,0xFF01,0x3FC0,0x3E80,0xFE41,
    0xFA01,0x3AC0,0x3B80,0xFB41,0x3900,0xF9C1,0xF881,0x3840,
    0x2800,0xE8C1,0xE981,0x2940,0xEB01,0x2BC0,0x2A80,0xEA41,
    0xEE01,0x2EC0,0x2F80,0xEF41,0x2D00,0xEDC1,0xEC81,0x2C40,
    0xE401,0x24C0,0x2580,0xE541,0x2700,0xE7C1,0xE681,0x2640,
    0x2200,0xE2C1,0xE381,0x2340,0xE101,0x21C0,0x2080,0xE041,
    0xA001,0x60C0,0x6180,0xA141,0x6300,0xA3C1,0xA281,0x6240,
    0x6600,0xA6C1,0xA781,0x6740,0xA501,0x65C0,0x6480,0xA441,
    0x6C00,0xACC1,0xAD81,0x6D40,0xAF01,0x6FC0,0x6E80,0xAE41,
    0xAA01,0x6AC0,0x6B80,0xAB41,0x6900,0xA9C1,0xA881,0x6840,
    0x7800,0xB8C1,0xB981,0x7940,0xBB01,0x7BC0,0x7A80,0xBA41,
    0xBE01,0x7EC0,0x7F80,0xBF41,0x7D00,0xBDC1,0xBC81,0x7C40,
    0xB401,0x74C0,0x7580,0xB541,0x7700,0xB7C1,0xB681,0x7640,
    0x7200,0xB2C1,0xB381,0x7340,0xB101,0x71C0,0x7080,0xB041,
    0x5000,0x90C1,0x9181,0x5140,0x9301,0x53C0,0x5280,0x9241,
    0x9601,0x56C0,0x5780,0x9741,0x5500,0x95C1,0x9481,0x5440,
    0x9C01,0x5CC0,0x5D80,0x9D41,0x5F00,0x9FC1,0x9E81,0x5E40,
    0x5A00,0x9AC1,0x9B81,0x5B40,0x9901,0x59C0,0x5880,0x9841,
    0x8801,0x48C0,0x4980,0x8941,0x4B00,0x8BC1,0x8A81,0x4A40,
    0x4E00,0x8EC1,0x8F81,0x4F40,0x8D01,0x4DC0,0x4C80,0x8C41,
    0x4400,0x84C1,0x8581,0x4540,0x8701,0x47C0,0x4680,0x8641,
    0x8201,0x42C0,0x4380,0x8341,0x4100,0x81C1,0x8081,0x4040,
]

def crc16_ibm(data: bytes) -> int:
    """CRC-16-IBM (MODBUS style). Matches crc16.c on firmware."""
    crc = 0xFFFF
    for b in data:
        crc = (crc >> 8) ^ _CRC16_TABLE[(crc ^ b) & 0xFF]
    return crc


# ── Frame building / parsing ──────────────────────────────────────

def build_frame_header(frame_type: int, payload_len: int, timestamp: int) -> bytes:
    """Return 13-byte header: SYNC(2) + TYPE(1) + LEN(2 BE) + TS(8 LE)."""
    return (struct.pack('<BB', SYNC_0, SYNC_1) +
            bytes([frame_type]) +
            struct.pack('>H', payload_len) +
            struct.pack('<Q', timestamp))


def build_frame(frame_type: int, timestamp: int, payload: bytes) -> bytes:
    """Return a complete frame with CRC16."""
    header = build_frame_header(frame_type, len(payload), timestamp)
    crc = crc16_ibm(header + payload)
    return header + payload + struct.pack('<H', crc)


def build_command(cmd_id: int, data: bytes = b'') -> bytes:
    """Build a TYPE=0x03 command frame."""
    payload = bytes([cmd_id]) + data
    return build_frame(TYPE_COMMAND, 0, payload)


@dataclass
class ParsedFrame:
    type: int
    timestamp: int          # microseconds (ESP32 system time)
    payload: bytes          # raw payload bytes
    crc_valid: bool


@dataclass
class SensorData:
    """Parsed TYPE=0x01 sensor frame."""
    seq_id: int
    active_channels: int
    eeg_raw: bytes               # 24ch × 3B = 72B raw (Big-endian 24-bit)
    mic_samples: bytes            # 64 × 2B = 128B raw PCM (little-endian 16-bit)
    quat_w: float
    quat_x: float
    quat_y: float
    quat_z: float
    timestamp: int                # original ESP32 timestamp


# ── Frame parser state machine ────────────────────────────────────

class FrameParser:
    """State machine that scans a byte stream for valid protocol frames."""

    def __init__(self):
        self._buf = bytearray()
        self._sync0_pos: Optional[int] = None

    def feed(self, data: bytes) -> list[ParsedFrame]:
        """Ingest raw bytes; return list of complete, CRC-valid ParsedFrame."""
        self._buf.extend(data)
        frames: list[ParsedFrame] = []

        while True:
            # Scan for SYNC0
            if self._sync0_pos is None:
                for i in range(len(self._buf)):
                    if self._buf[i] == SYNC_0:
                        self._sync0_pos = i
                        break
                if self._sync0_pos is None:
                    self._buf.clear()
                    return frames
                # Discard bytes before SYNC0
                if self._sync0_pos > 0:
                    del self._buf[:self._sync0_pos]
                    self._sync0_pos = 0

            # Need at least PROTO_HEADER_SIZE bytes for header
            if len(self._buf) < self._sync0_pos + PROTO_HEADER_SIZE:
                return frames

            hdr_start = self._sync0_pos
            sync0 = self._buf[hdr_start + 0]
            sync1 = self._buf[hdr_start + 1]
            if sync0 != SYNC_0 or sync1 != SYNC_1:
                # false sync0 — skip it
                self._sync0_pos = None
                del self._buf[0:1]
                continue

            frame_type = self._buf[hdr_start + 2]
            payload_len = struct.unpack('>H', self._buf[hdr_start + 3:hdr_start + 5])[0]

            frame_total = PROTO_HEADER_SIZE + payload_len + PROTO_CRC_SIZE
            if len(self._buf) - hdr_start < frame_total:
                return frames  # incomplete frame, wait for more data

            # Extract full header+payload for CRC check
            header_and_payload = self._buf[hdr_start:hdr_start + PROTO_HEADER_SIZE + payload_len]
            crc_bytes = self._buf[hdr_start + PROTO_HEADER_SIZE + payload_len:
                                  hdr_start + frame_total]
            expected_crc = struct.unpack('<H', bytes(crc_bytes))[0]

            actual_crc = crc16_ibm(bytes(header_and_payload))

            timestamp = struct.unpack('<Q', self._buf[hdr_start + 5:hdr_start + 13])[0]
            payload = bytes(self._buf[hdr_start + 13:hdr_start + 13 + payload_len])

            frames.append(ParsedFrame(
                type=frame_type,
                timestamp=timestamp,
                payload=payload,
                crc_valid=(actual_crc == expected_crc),
            ))

            # Advance past this frame
            self._buf = self._buf[hdr_start + frame_total:]
            self._sync0_pos = None

    def feed_one(self, data: bytes) -> Optional[ParsedFrame]:
        """Convenience: feed and return at most one frame (block until at least one)."""
        frames = self.feed(data)
        return frames[0] if frames else None


def parse_sensor_data(frame: ParsedFrame) -> Optional[SensorData]:
    """Parse a SENSOR_DATA (TYPE=0x01) payload into structured fields."""
    if frame.type != TYPE_SENSOR or not frame.crc_valid:
        return None
    payload = frame.payload
    if len(payload) < SENSOR_PAYLOAD_SIZE:
        return None

    offset = 0
    seq_id = struct.unpack_from('<H', payload, offset)[0]; offset += 2
    active_channels = payload[offset]; offset += 1
    offset += 1  # reserved

    eeg_raw = payload[offset:offset + EEG_DATA_BYTES]; offset += EEG_DATA_BYTES

    mic_sample_count = struct.unpack_from('<H', payload, offset)[0]; offset += 2
    mic_data_len = mic_sample_count * 2  # 16-bit per sample
    mic_samples = payload[offset:offset + mic_data_len]; offset += mic_data_len

    quat_w = struct.unpack_from('<f', payload, offset)[0]; offset += 4
    quat_x = struct.unpack_from('<f', payload, offset)[0]; offset += 4
    quat_y = struct.unpack_from('<f', payload, offset)[0]; offset += 4
    quat_z = struct.unpack_from('<f', payload, offset)[0]; offset += 4

    return SensorData(
        seq_id=seq_id,
        active_channels=active_channels,
        eeg_raw=eeg_raw,
        mic_samples=mic_samples[:mic_data_len],
        quat_w=quat_w, quat_x=quat_x, quat_y=quat_y, quat_z=quat_z,
        timestamp=frame.timestamp,
    )
