"""Serve the browser EEG viewer and stream 16-channel LSL data over WebSocket."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import signal
import struct
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, request
from urllib.parse import urlparse

from .eeg_buffer import EEGBuffer
from .impedance_service import ImpedanceService
from .lsl_reader import LSLReader
from .recording_service import RecordingService


STATIC_DIR = Path(__file__).with_name("static").resolve()
UPLOAD_DIR = Path(tempfile.gettempdir()) / "earEEG_viewer_uploads"
CHANNELS = 16
SAMPLE_RATE = 250
MIC_CHANNELS = 1
MIC_SAMPLE_RATE = 16000


class ViewerHandler(BaseHTTPRequestHandler):
    eeg_buffer: EEGBuffer
    eeg_reader: LSLReader
    mic_buffer: EEGBuffer
    mic_reader: LSLReader
    impedance: ImpedanceService
    recorder: RecordingService
    proxy_url: str

    def do_GET(self) -> None:
        if self.headers.get("Upgrade", "").lower() == "websocket":
            self._serve_websocket()
            return

        path = urlparse(self.path).path
        if path == "/api/proxy/status":
            self._proxy_get("/status")
            return
        if path == "/api/impedance/status":
            self._send_json(self.impedance.status())
            return
        if path == "/api/recording/status":
            self._send_json(self.recorder.status())
            return

        if path == "/":
            path = "/index.html"
        file_path = (STATIC_DIR / path.lstrip("/")).resolve()
        if not file_path.is_file() or STATIC_DIR not in file_path.parents:
            if path.startswith("/api/"):
                self._send_json({"ok": False, "error": f"unknown API route: {path}"}, 404)
                return
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

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/audio/upload":
            self._handle_audio_upload()
        elif path == "/api/acquisition/start":
            self._proxy_post("/acquisition/start")
        elif path == "/api/acquisition/stop":
            self._proxy_post("/acquisition/stop")
        elif path == "/api/audio/play":
            body = self._read_json_body()
            payload, status = self._proxy_post_payload("/audio/play", body)
            self._send_json(payload, status)
            if status < 400 and payload.get("ok", True):
                self.recorder.stimulus_play(str(body.get("path", "")))
        elif path == "/api/audio/pause":
            payload, status = self._proxy_post_payload("/audio/pause")
            self._send_json(payload, status)
            if status < 400 and payload.get("ok", True):
                self.recorder.stimulus_pause()
        elif path == "/api/audio/resume":
            payload, status = self._proxy_post_payload("/audio/resume")
            self._send_json(payload, status)
            if status < 400 and payload.get("ok", True):
                self.recorder.stimulus_resume()
        elif path == "/api/audio/stop":
            payload, status = self._proxy_post_payload("/audio/stop")
            self._send_json(payload, status)
            if status < 400 and payload.get("ok", True):
                self.recorder.stimulus_stop()
        elif path == "/api/impedance/start":
            body = self._read_json_body()
            self._send_json(self.impedance.start(
                channels=str(body.get("channels", "1-8")),
                duration=float(body.get("duration", 3.0) or 3.0),
            ))
        elif path == "/api/impedance/stop":
            self._send_json(self.impedance.stop())
        elif path == "/api/recording/start":
            body = self._read_json_body()
            self._send_json(self.recorder.start(str(body.get("tag", ""))))
        elif path == "/api/recording/stop":
            self._send_json(self.recorder.stop())
        else:
            if path.startswith("/api/"):
                self._send_json({"ok": False, "error": f"unknown API route: {path}"}, 404)
                return
            self.send_error(404)

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

        last_eeg_total = -1
        last_mic_total = -1
        try:
            while True:
                if last_eeg_total < 0:
                    eeg_samples, eeg_total = self.eeg_buffer.snapshot(10.0)
                else:
                    eeg_samples, eeg_total = self.eeg_buffer.snapshot_since(last_eeg_total)
                last_eeg_total = eeg_total

                if last_mic_total < 0:
                    mic_samples, mic_total = self.mic_buffer.snapshot(2.0)
                else:
                    mic_samples, mic_total = self.mic_buffer.snapshot_since(last_mic_total)
                last_mic_total = mic_total

                payload = json.dumps({
                    "channels": CHANNELS,
                    "sampleRate": SAMPLE_RATE,
                    "sampleCount": eeg_total,
                    "lslConnected": self.eeg_reader.connected,
                    "proxy": self._read_proxy_status(),
                    "error": self.eeg_reader.last_error,
                    "samples": eeg_samples.T.tolist(),
                    "mic": {
                        "channels": MIC_CHANNELS,
                        "sampleRate": MIC_SAMPLE_RATE,
                        "sampleCount": mic_total,
                        "lslConnected": self.mic_reader.connected,
                        "error": self.mic_reader.last_error,
                        "samples": mic_samples[:, 0].tolist(),
                    },
                }, separators=(",", ":")).encode("utf-8")
                self.wfile.write(_websocket_frame(payload))
                self.wfile.flush()
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _read_proxy_status(self) -> dict:
        try:
            with request.urlopen(f"{self.proxy_url}/status", timeout=0.2) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"connected": False, "acquiring": False, "lastError": "proxy unavailable"}

    def _proxy_get(self, path: str) -> None:
        try:
            with request.urlopen(f"{self.proxy_url}{path}", timeout=1.0) as resp:
                self._send_json(json.loads(resp.read().decode("utf-8")), resp.status)
        except error.HTTPError as exc:
            self._send_json(_json_error(exc), exc.code)
        except OSError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 502)

    def _proxy_post(self, path: str, body: dict | None = None) -> None:
        payload, status = self._proxy_post_payload(path, body)
        self._send_json(payload, status)

    def _proxy_post_payload(self, path: str, body: dict | None = None) -> tuple[dict, int]:
        data = json.dumps(body or {}, separators=(",", ":")).encode("utf-8")
        req = request.Request(f"{self.proxy_url}{path}", data=data, method="POST",
                              headers={"Content-Type": "application/json"})
        try:
            with request.urlopen(req, timeout=1.0) as resp:
                return json.loads(resp.read().decode("utf-8")), resp.status
        except error.HTTPError as exc:
            return _json_error(exc), exc.code
        except OSError as exc:
            return {"ok": False, "error": str(exc)}, 502

    def _handle_audio_upload(self) -> None:
        filename = _safe_upload_name(self.headers.get("X-File-Name", "audio.wav"))
        if not filename.lower().endswith(".wav"):
            self._send_json({"ok": False, "error": "only WAV files are supported"}, 400)
            return

        try:
            remaining = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            remaining = 0
        if remaining <= 0:
            self._send_json({"ok": False, "error": "empty upload"}, 400)
            return

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        path = UPLOAD_DIR / f"{uuid.uuid4().hex}_{filename}"
        try:
            with path.open("wb") as out:
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
        except OSError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        self._send_json({"ok": True, "path": str(path), "fileName": filename})

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def _send_json(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _json_error(exc: error.HTTPError) -> dict:
    try:
        return json.loads(exc.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "error": str(exc)}


def _safe_upload_name(name: str) -> str:
    filename = Path(name).name or "audio.wav"
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
    return filename or "audio.wav"


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
    parser.add_argument("--proxy-url", default="http://127.0.0.1:8787",
                        help="lsl_proxy control URL (default: http://127.0.0.1:8787)")
    args = parser.parse_args()

    eeg_buffer = EEGBuffer(channels=CHANNELS, sample_rate=SAMPLE_RATE)
    mic_buffer = EEGBuffer(channels=MIC_CHANNELS, sample_rate=MIC_SAMPLE_RATE,
                           capacity_seconds=10)
    recorder = RecordingService(Path("recordings"))
    eeg_reader = LSLReader(eeg_buffer, stream_name="earEEG_EEG", max_samples=128,
                           on_samples=recorder.append_eeg)
    mic_reader = LSLReader(mic_buffer, stream_name="earEEG_Audio", max_samples=2048,
                           on_samples=recorder.append_mic)
    ViewerHandler.eeg_buffer = eeg_buffer
    ViewerHandler.eeg_reader = eeg_reader
    ViewerHandler.mic_buffer = mic_buffer
    ViewerHandler.mic_reader = mic_reader
    ViewerHandler.proxy_url = args.proxy_url.rstrip("/")
    ViewerHandler.impedance = ImpedanceService(eeg_buffer, ViewerHandler.proxy_url)
    ViewerHandler.recorder = recorder
    server = ThreadingHTTPServer((args.host, args.port), ViewerHandler)
    eeg_reader.start()
    mic_reader.start()

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
        eeg_reader.stop()
        mic_reader.stop()
        server.server_close()


if __name__ == "__main__":
    main()
