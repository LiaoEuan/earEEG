"""Realtime EEG server -- HTTP + WebSocket + processing main loop.

Reads EEG from LSL, processes through pipeline, pushes results via WebSocket.

Usage:
    python -m ear_eeg_sound_lab.src.web_app.server --port 8765
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import signal
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ear_eeg_sound_lab.src.integrations.lsl_buffer import EEGRollingBuffer
from ear_eeg_sound_lab.src.integrations.lsl_reader import LSLStreamReader
from ear_eeg_sound_lab.src.realtime_engine.pipeline import process_window
from ear_eeg_sound_lab.src.web_app.recording_service import RecordingService
from ear_eeg_sound_lab.src.web_app.state_provider import DashboardStateProvider

STATIC_DIR = Path(__file__).with_name("static").resolve()


def _websocket_frame(payload: bytes) -> bytes:
    """Encode a payload as a WebSocket text frame (server to client)."""
    if len(payload) < 126:
        return struct.pack("!BB", 0x81, len(payload)) + payload
    if len(payload) <= 0xFFFF:
        return struct.pack("!BBH", 0x81, 126, len(payload)) + payload
    return struct.pack("!BBQ", 0x81, 127, len(payload)) + payload


class RealtimeHandler(BaseHTTPRequestHandler):
    """HTTP request handler with WebSocket upgrade support."""

    state_provider: DashboardStateProvider
    recorder: RecordingService

    def log_message(self, fmt: str, *args) -> None:
        if args and str(args[1]) == "101":
            print("[server] WebSocket client connected")

    def do_GET(self) -> None:
        if self.headers.get("Upgrade", "").lower() == "websocket":
            self._serve_websocket()
            return

        if self.path == "/api/state":
            self._send_json(self.state_provider.get_state())
            return

        if self.path == "/api/recording/status":
            self._send_json(self.recorder.status())
            return

        if self.path == "/api/recordings":
            self._send_json({"recordings": self.recorder.list_recordings()})
            return

        if self.path == "/" or self.path == "/index.html":
            self._serve_file(STATIC_DIR / "index.html", "text/html")
            return

        self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/api/recording/start":
            result = self.recorder.start(sample_rate=self.state_provider._sample_rate)
            self._send_json(result)
            return
        if self.path == "/api/recording/stop":
            result = self.recorder.stop()
            self._send_json(result)
            return
        self.send_error(404)

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj: dict) -> None:
        data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_websocket(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self.send_error(400, "missing WebSocket key")
            return
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
        ).digest()).decode("ascii")
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()

        try:
            while True:
                state = self.state_provider.get_state()
                state["recording"] = self.recorder.status()
                payload = json.dumps(state, separators=(",", ":")).encode("utf-8")
                self.wfile.write(_websocket_frame(payload))
                self.wfile.flush()
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


class RealtimeServer:
    """Main server that runs LSL processing loop and HTTP/WS service.

    Args:
        host: HTTP server bind address.
        port: HTTP server port.
        stream_name: LSL stream name to search for.
        stream_type: LSL stream type (fallback).
        channels: Number of EEG channels.
        sample_rate: EEG sampling rate in Hz.
        window_seconds: Processing window length in seconds.
        step_seconds: Processing step size in seconds.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        stream_name: str = "earEEG_EEG",
        stream_type: str = "EEG",
        channels: int = 16,
        sample_rate: float = 250.0,
        window_seconds: float = 2.0,
        step_seconds: float = 0.5,
    ) -> None:
        self.host = host
        self.port = port
        self.stream_name = stream_name
        self.stream_type = stream_type
        self.channels = channels
        self.sample_rate = sample_rate
        self.window_seconds = window_seconds
        self.step_seconds = step_seconds

        self.state_provider = DashboardStateProvider(
            waveform_seconds=window_seconds,
            channels=channels,
            sample_rate=sample_rate,
        )
        self.recorder = RecordingService(output_dir="recordings")
        self._stop_event = threading.Event()

    def run(self) -> None:
        """Start the server: LSL connection + HTTP/WS service + processing loop."""
        RealtimeHandler.state_provider = self.state_provider
        RealtimeHandler.recorder = self.recorder

        httpd = ThreadingHTTPServer((self.host, self.port), RealtimeHandler)
        http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        http_thread.start()
        print(f"[server] HTTP/WS listening on http://{self.host}:{self.port}")

        reader = LSLStreamReader(
            stream_name=self.stream_name,
            stream_type=self.stream_type,
            expected_channels=self.channels,
        )
        buffer = EEGRollingBuffer(
            channels=self.channels,
            sample_rate=self.sample_rate,
            capacity_seconds=30.0,
        )

        print(f"[server] Searching for LSL stream '{self.stream_name}'...")
        connected = False
        while not self._stop_event.is_set():
            if not connected:
                try:
                    reader.connect(timeout=3.0)
                    connected = True
                    self.state_provider.set_device_status(
                        connected=True,
                        stream_name=self.stream_name,
                        sample_rate=self.sample_rate,
                        channels=self.channels,
                    )
                    print(f"[server] Connected to LSL stream '{self.stream_name}'")
                except RuntimeError:
                    print("[server] LSL stream not found, retrying...")
                    time.sleep(1)
                    continue

            try:
                chunk = reader.pull_chunk(max_samples=128, timeout=0.1)
            except Exception as e:
                print(f"[server] LSL pull error: {e}")
                connected = False
                self.state_provider.set_device_status(connected=False)
                time.sleep(1)
                continue

            if chunk is None:
                continue

            buffer.append_chunk(chunk)

            window = buffer.pop_next_window(
                window_seconds=self.window_seconds,
                step_seconds=self.step_seconds,
            )
            if window is not None:
                try:
                    output = process_window(window)
                    self.state_provider.update(output)
                    self.recorder.append_eeg(output.window.data)
                except Exception as e:
                    print(f"[server] Pipeline error: {e}")

        httpd.shutdown()
        print("[server] Stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="earEEG realtime server")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP server host")
    parser.add_argument("--port", type=int, default=8765, help="HTTP server port")
    parser.add_argument("--stream-name", default="earEEG_EEG", help="LSL stream name")
    parser.add_argument("--channels", type=int, default=16, help="EEG channels")
    parser.add_argument("--sample-rate", type=float, default=250.0, help="EEG sample rate")
    args = parser.parse_args()

    server = RealtimeServer(
        host=args.host,
        port=args.port,
        stream_name=args.stream_name,
        channels=args.channels,
        sample_rate=args.sample_rate,
    )

    def handle_sigint(*_):
        print("\n[server] Shutting down...")
        server._stop_event.set()

    signal.signal(signal.SIGINT, handle_sigint)
    server.run()


if __name__ == "__main__":
    main()
