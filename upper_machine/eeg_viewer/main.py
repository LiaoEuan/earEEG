"""Serve the browser EEG viewer and stream 16-channel LSL data over WebSocket."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import signal
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .eeg_buffer import EEGBuffer
from .lsl_reader import LSLReader


STATIC_DIR = Path(__file__).with_name("static").resolve()
CHANNELS = 16
SAMPLE_RATE = 250


class ViewerHandler(BaseHTTPRequestHandler):
    buffer: EEGBuffer
    reader: LSLReader

    def do_GET(self) -> None:
        if self.headers.get("Upgrade", "").lower() == "websocket":
            self._serve_websocket()
            return

        path = urlparse(self.path).path
        if path == "/":
            path = "/index.html"
        file_path = (STATIC_DIR / path.lstrip("/")).resolve()
        if not file_path.is_file() or STATIC_DIR not in file_path.parents:
            self.send_error(404)
            return

        content_type = "text/html; charset=utf-8"
        if file_path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        if args and str(args[1]) == "101":
            print("[viewer] browser WebSocket connected")

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

        last_total = -1
        try:
            while True:
                if last_total < 0:
                    samples, total = self.buffer.snapshot(10.0)
                else:
                    samples, total = self.buffer.snapshot_since(last_total)
                last_total = total
                payload = json.dumps({
                    "channels": CHANNELS,
                    "sampleRate": SAMPLE_RATE,
                    "sampleCount": total,
                    "lslConnected": self.reader.connected,
                    "error": self.reader.last_error,
                    "samples": samples.T.tolist(),
                }, separators=(",", ":")).encode("utf-8")
                self.wfile.write(_websocket_frame(payload))
                self.wfile.flush()
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


def _websocket_frame(payload: bytes) -> bytes:
    if len(payload) < 126:
        return struct.pack("!BB", 0x81, len(payload)) + payload
    if len(payload) <= 0xFFFF:
        return struct.pack("!BBH", 0x81, 126, len(payload)) + payload
    return struct.pack("!BBQ", 0x81, 127, len(payload)) + payload


def main() -> None:
    parser = argparse.ArgumentParser(description="earEEG browser viewer")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    buffer = EEGBuffer(channels=CHANNELS, sample_rate=SAMPLE_RATE)
    reader = LSLReader(buffer)
    ViewerHandler.buffer = buffer
    ViewerHandler.reader = reader
    server = ThreadingHTTPServer((args.host, args.port), ViewerHandler)
    reader.start()

    stopping = threading.Event()

    def stop(*_args) -> None:
        if not stopping.is_set():
            stopping.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f"[viewer] open http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    finally:
        reader.stop()
        server.server_close()


if __name__ == "__main__":
    main()
