"""Local HTTP control API for the long-running lsl_proxy process."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from .audio_player import AudioPlayer
from .tcp_client import TCPClient


@dataclass
class ProxyStatus:
    connected: bool
    acquiring: bool
    frame_count: int
    lost_packets: int
    fps: float
    loss_percent: float
    last_error: str


class ProxyController:
    """Thread-safe command surface around the single TCP client."""

    def __init__(self, client: TCPClient, status_provider: Callable[[], ProxyStatus]):
        self._client = client
        self._status_provider = status_provider
        self._lock = threading.Lock()
        self._acquiring = False
        self._last_error = ""
        self._audio_player: Optional[AudioPlayer] = None

    @property
    def acquiring(self) -> bool:
        with self._lock:
            return self._acquiring

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def mark_disconnected(self) -> None:
        with self._lock:
            self._acquiring = False

    def start_acquisition(self) -> dict:
        with self._lock:
            if not self._client.connected:
                return self._error("device is not connected")
            if not self._client.start_acquisition():
                return self._error("failed to send START_ACQ")
            self._acquiring = True
            self._last_error = ""
            return {"ok": True, "acquiring": True}

    def stop_acquisition(self) -> dict:
        with self._lock:
            if not self._client.connected:
                self._acquiring = False
                return self._error("device is not connected")
            if not self._client.stop_acquisition():
                return self._error("failed to send STOP_ACQ")
            self._acquiring = False
            self._last_error = ""
            return {"ok": True, "acquiring": False}

    def set_impedance(self, command: str) -> dict:
        with self._lock:
            if not self._client.connected:
                return self._error("device is not connected")
            if not command:
                return self._error("missing impedance command")
            try:
                sent = self._client.set_impedance(command)
            except UnicodeEncodeError:
                return self._error("impedance command must be ASCII")
            if not sent:
                return self._error("failed to send impedance command")
            self._last_error = ""
            return {"ok": True, "command": command}

    def stop_impedance(self) -> dict:
        with self._lock:
            if not self._client.connected:
                return self._error("device is not connected")
            if not self._client.stop_impedance():
                return self._error("failed to send IMPEDANCE_STOP")
            self._last_error = ""
            return {"ok": True}

    def play_audio(self, wav_path: str, prefill_ms: int = 500, batch_ms: int = 50) -> dict:
        with self._lock:
            if not self._client.connected:
                return self._error("device is not connected")
            path = Path(wav_path).expanduser().resolve()
            if not path.is_file():
                return self._error(f"audio file not found: {path}")
            self._stop_audio_locked()
            self._audio_player = AudioPlayer(
                self._client,
                str(path),
                prefill_ms=prefill_ms,
                batch_ms=batch_ms,
            )
            self._audio_player.start()
            self._last_error = ""
            return {"ok": True, "audio": self.audio_status()}

    def pause_audio(self) -> dict:
        with self._lock:
            if not self._audio_player or not self._audio_player.running:
                return self._error("no audio playback is running")
            self._audio_player.pause()
            self._last_error = ""
            return {"ok": True, "audio": self.audio_status()}

    def resume_audio(self) -> dict:
        with self._lock:
            if not self._audio_player or not self._audio_player.running:
                return self._error("no audio playback is running")
            self._audio_player.resume()
            self._last_error = ""
            return {"ok": True, "audio": self.audio_status()}

    def stop_audio(self) -> dict:
        with self._lock:
            self._stop_audio_locked()
            self._last_error = ""
            return {"ok": True, "audio": self.audio_status()}

    def audio_status(self) -> dict:
        player = self._audio_player
        if not player:
            return {
                "playing": False,
                "paused": False,
                "fileName": "",
                "lastError": "",
            }
        if player.finished:
            last_error = player.last_error
            self._audio_player = None
            return {
                "playing": False,
                "paused": False,
                "fileName": "",
                "lastError": last_error,
            }
        return {
            "playing": player.running,
            "paused": player.paused,
            "fileName": player.file_name,
            "lastError": player.last_error,
        }

    def status(self) -> dict:
        status = self._status_provider()
        return {
            "connected": status.connected,
            "acquiring": status.acquiring,
            "frameCount": status.frame_count,
            "lostPackets": status.lost_packets,
            "fps": status.fps,
            "lossPercent": status.loss_percent,
            "lastError": status.last_error,
            "audio": self.audio_status(),
        }

    def _error(self, message: str) -> dict:
        self._last_error = message
        return {"ok": False, "error": message}

    def _stop_audio_locked(self) -> None:
        if self._audio_player:
            self._audio_player.stop()
            self._audio_player = None


class ControlServer:
    def __init__(self, host: str, port: int, controller: ProxyController):
        self._host = host
        self._port = port
        self._controller = controller
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        handler = _make_handler(self._controller)
        self._server = ThreadingHTTPServer((self._host, self._port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"[control] listening on http://{self._host}:{self._port}")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)


def _make_handler(controller: ProxyController):
    class ControlHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:
            self._send_json({"ok": True})

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/status":
                self._send_json(controller.status())
                return
            self.send_error(404)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            body = self._read_json_body()
            if path == "/acquisition/start":
                self._send_result(controller.start_acquisition())
            elif path == "/acquisition/stop":
                self._send_result(controller.stop_acquisition())
            elif path == "/audio/play":
                self._send_result(controller.play_audio(
                    str(body.get("path", "")),
                    prefill_ms=int(body.get("prefillMs", 500) or 500),
                    batch_ms=int(body.get("batchMs", 50) or 50),
                ))
            elif path == "/audio/pause":
                self._send_result(controller.pause_audio())
            elif path == "/audio/resume":
                self._send_result(controller.resume_audio())
            elif path == "/audio/stop":
                self._send_result(controller.stop_audio())
            elif path == "/impedance/control":
                self._send_result(controller.set_impedance(str(body.get("command", ""))))
            elif path == "/impedance/stop":
                self._send_result(controller.stop_impedance())
            else:
                self.send_error(404)

        def log_message(self, fmt: str, *args) -> None:
            return

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}

        def _send_result(self, payload: dict) -> None:
            self._send_json(payload, status=200 if payload.get("ok", True) else 400)

        def _send_json(self, payload: dict, status: int = 200) -> None:
            raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(raw)

    return ControlHandler
