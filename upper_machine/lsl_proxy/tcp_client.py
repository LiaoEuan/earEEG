"""
TCP client for connecting to the ESP32 earEEG device.
Handles connection lifecycle, frame receiving, and command sending.
"""

import socket
import struct
import threading
import time
from typing import Optional, Callable

from upper_machine.common.protocol import (
    FrameParser, ParsedFrame, SensorData,
    build_command, parse_sensor_data,
    TYPE_SENSOR, TYPE_ACK, TYPE_COMMAND,
    CMD_START_ACQ, CMD_STOP_ACQ,
)


class TCPClient:
    """Manages a TCP connection to the ESP32 server."""

    def __init__(self, host: str, port: int = 8888):
        self._host = host
        self._port = port
        self._sock: Optional[socket.socket] = None
        self._parser = FrameParser()
        self._recv_thread: Optional[threading.Thread] = None
        self._running = False
        self._on_sensor: Optional[Callable[[SensorData], None]] = None
        self._on_frame: Optional[Callable[[ParsedFrame], None]] = None

    # ── public API ──────────────────────────────────────────────

    def connect(self, timeout: float = 10.0) -> bool:
        """Open TCP connection. Returns True on success."""
        try:
            self._sock = socket.create_connection((self._host, self._port), timeout=timeout)
            self._sock.settimeout(0.5)
            self._running = True
            self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._recv_thread.start()
            return True
        except (OSError, TimeoutError) as e:
            print(f"[TCP] connect failed: {e}")
            return False

    def disconnect(self):
        """Close connection and stop receive thread."""
        self._running = False
        if self._recv_thread and self._recv_thread.is_alive():
            self._recv_thread.join(timeout=1.0)
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    @property
    def connected(self) -> bool:
        return self._sock is not None and self._running

    # ── frame send ──────────────────────────────────────────────

    def send_raw(self, data: bytes) -> bool:
        """Send raw bytes. Returns True on success."""
        if not self._sock:
            return False
        try:
            self._sock.sendall(data)
            return True
        except OSError:
            return False

    def send_command(self, cmd_id: int, data: bytes = b'') -> bool:
        """Build and send a CMD frame (TYPE=0x03)."""
        return self.send_raw(build_command(cmd_id, data))

    def start_acquisition(self):
        """Send CMD_START_ACQ (0x01)."""
        return self.send_command(CMD_START_ACQ)

    def stop_acquisition(self):
        """Send CMD_STOP_ACQ (0x02)."""
        return self.send_command(CMD_STOP_ACQ)

    # ── callbacks ───────────────────────────────────────────────

    def on_sensor_data(self, callback: Optional[Callable[[SensorData], None]]):
        """Register callback for parsed TYPE=0x01 sensor frames."""
        self._on_sensor = callback

    def on_frame(self, callback: Optional[Callable[[ParsedFrame], None]]):
        """Register callback for every valid frame (any TYPE)."""
        self._on_frame = callback

    # ── internal recv loop ──────────────────────────────────────

    def _recv_loop(self):
        buf = bytearray(4096)
        last_ack_time = 0.0
        while self._running and self._sock:
            try:
                n = self._sock.recv_into(buf)
                if n == 0:
                    print("[TCP] server closed connection")
                    self._running = False
                    break
                if n < 0:
                    continue

                frames = self._parser.feed(bytes(buf[:n]))
                for frame in frames:
                    if not frame.crc_valid:
                        print(f"[TCP] CRC mismatch on TYPE=0x{frame.type:02X}")
                        continue

                    if self._on_frame:
                        self._on_frame(frame)

                    if frame.type == TYPE_SENSOR:
                        sensor = parse_sensor_data(frame)
                        if sensor and self._on_sensor:
                            self._on_sensor(sensor)

                    elif frame.type == TYPE_ACK:
                        # ACK payload: [cmd_id 1B][status 1B]
                        if len(frame.payload) >= 2:
                            cmd_id = frame.payload[0]
                            status = frame.payload[1]
                            print(f"[TCP] ACK cmd=0x{cmd_id:02X} status={status}")
            except socket.timeout:
                continue
            except OSError as e:
                if self._running:
                    print(f"[TCP] recv error: {e}")
                self._running = False
                break
