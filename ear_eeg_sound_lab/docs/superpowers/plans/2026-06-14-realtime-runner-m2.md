# Realtime Runner (M2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现实时运行器 — LSL → pipeline → WebSocket → 浏览器 UI，完成 Milestone 2

**Architecture:** 独立 HTTP+WebSocket 服务，主循环从 LSL 读取 EEG，通过 pipeline 处理，WebSocket 推送结果到浏览器。用标准库实现 WebSocket（参考 eeg_viewer）。

**Tech Stack:** Python 3.14+, numpy, 标准库 (http.server, hashlib, struct, json, threading)

**Design Spec:** `ear_eeg_sound_lab/docs/superpowers/specs/2026-06-14-realtime-runner-m2-design.md`

---

## 文件结构总览

```
ear_eeg_sound_lab/src/web_app/
  __init__.py              (新建)
  server.py                (新建)
  state_provider.py        (新建)
  static/
    index.html             (新建)
ear_eeg_sound_lab/tests/
  test_state_provider.py   (新建)
  test_server.py           (新建, 可选)
```

---

### Task 1: state_provider.py — 状态汇聚

**Files:**
- Create: `ear_eeg_sound_lab/src/web_app/__init__.py`
- Create: `ear_eeg_sound_lab/src/web_app/state_provider.py`
- Create: `ear_eeg_sound_lab/tests/test_state_provider.py`

- [ ] **Step 1: 创建 web_app 包**

```python
# ear_eeg_sound_lab/src/web_app/__init__.py
```

（空文件）

- [ ] **Step 2: 编写 test_state_provider.py**

```python
"""Tests for state_provider module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    BandPower,
    EEGWindow,
    EngineOutput,
    FeatureFrame,
    FocusEstimate,
    PreprocessedWindow,
    SignalQuality,
)
from ear_eeg_sound_lab.src.web_app.state_provider import DashboardStateProvider


def _make_engine_output(
    focus_score: int = 70,
    focus_state: str = "focused",
    quality_score: float = 0.9,
    n_channels: int = 16,
    n_samples: int = 500,
) -> EngineOutput:
    """Helper to create a synthetic EngineOutput."""
    data = np.random.randn(n_channels, n_samples)
    window = EEGWindow(
        data=data, sample_rate=250.0,
        start_sample=0, start_time=0.0, unit="uv",
    )
    preprocessed = PreprocessedWindow(raw=window, data=data)
    features = FeatureFrame(
        timestamp=0.0,
        global_band_powers=BandPower(delta=10, theta=8, alpha=15, beta=20, gamma=3),
        theta_beta_ratio=0.4,
        alpha_beta_ratio=0.75,
        artifact_ratio=0.05,
    )
    quality = SignalQuality(score=quality_score, bad_channels=[], warnings=[])
    focus = FocusEstimate(score=focus_score, quality=quality_score, state=focus_state, reasons=["beta_present"])
    return EngineOutput(window=window, preprocessed=preprocessed, features=features, quality=quality, focus=focus)


class TestDashboardStateProvider(unittest.TestCase):

    def test_initial_state(self):
        """初始状态应返回空数据。"""
        provider = DashboardStateProvider(channels=16)
        state = provider.get_state()

        self.assertEqual(state["focus"]["score"], 0)
        self.assertEqual(state["device"]["connected"], False)

    def test_update_focus(self):
        """update 后 get_state 应反映最新 focus。"""
        provider = DashboardStateProvider(channels=16)
        output = _make_engine_output(focus_score=85, focus_state="focused")
        provider.update(output)

        state = provider.get_state()
        self.assertEqual(state["focus"]["score"], 85)
        self.assertEqual(state["focus"]["state"], "focused")

    def test_update_quality(self):
        """update 后 get_state 应反映最新 quality。"""
        provider = DashboardStateProvider(channels=16)
        output = _make_engine_output(quality_score=0.75)
        provider.update(output)

        state = provider.get_state()
        self.assertAlmostEqual(state["focus"]["quality"], 0.75)

    def test_update_band_powers(self):
        """update 后 get_state 应包含频段功率。"""
        provider = DashboardStateProvider(channels=16)
        output = _make_engine_output()
        provider.update(output)

        state = provider.get_state()
        bp = state["features"]["globalBandPowers"]
        self.assertIn("delta", bp)
        self.assertIn("theta", bp)
        self.assertIn("alpha", bp)
        self.assertIn("beta", bp)
        self.assertIn("gamma", bp)

    def test_waveform_rolling(self):
        """波形应滚动保留最近 N 秒。"""
        provider = DashboardStateProvider(channels=4, waveform_seconds=1.0)

        # 每次 500 samples (2s)，但只保留 1s = 250 samples
        for i in range(5):
            output = _make_engine_output(n_channels=4, n_samples=500)
            provider.update(output)

        state = provider.get_state()
        eeg = state["eeg"]
        # 应该只保留最近 250 samples
        self.assertLessEqual(len(eeg["samples"][0]), 250 + 500)  # allow some buffer

    def test_device_status(self):
        """set_device_status 应更新设备信息。"""
        provider = DashboardStateProvider(channels=16)
        provider.set_device_status(connected=True, stream_name="earEEG_EEG", sample_rate=250.0, channels=16)

        state = provider.get_state()
        self.assertEqual(state["device"]["connected"], True)
        self.assertEqual(state["device"]["streamName"], "earEEG_EEG")

    def test_timestamp_present(self):
        """状态应包含 timestamp。"""
        provider = DashboardStateProvider(channels=16)
        output = _make_engine_output()
        provider.update(output)

        state = provider.get_state()
        self.assertIn("timestamp", state)
        self.assertIsInstance(state["timestamp"], float)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行测试确认失败**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_state_provider -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 4: 实现 state_provider.py**

```python
"""Dashboard state provider — aggregates EngineOutput into WebSocket-ready state.

Maintains rolling EEG waveform buffer and latest focus/quality/features.
Thread-safe: update() is called from the processing thread,
get_state() is called from the WebSocket handler thread.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import EngineOutput


class DashboardStateProvider:
    """Aggregates pipeline outputs into a single dashboard state dict.

    Args:
        waveform_seconds: How many seconds of EEG waveform to keep.
        channels: Number of EEG channels.
        sample_rate: EEG sampling rate in Hz.
    """

    def __init__(
        self,
        waveform_seconds: float = 2.0,
        channels: int = 16,
        sample_rate: float = 250.0,
    ) -> None:
        self._waveform_samples = int(waveform_seconds * sample_rate)
        self._channels = channels
        self._sample_rate = sample_rate
        self._lock = threading.Lock()

        # Latest state
        self._focus: dict = {"score": 0, "quality": 0.0, "state": "unknown", "reasons": []}
        self._features: dict = {
            "globalBandPowers": {"delta": 0, "theta": 0, "alpha": 0, "beta": 0, "gamma": 0},
            "thetaBetaRatio": 0.0,
            "alphaBetaRatio": 0.0,
            "artifactRatio": 0.0,
        }
        self._device: dict = {
            "connected": False,
            "streamName": "",
            "sampleRate": sample_rate,
            "channels": channels,
        }

        # Rolling waveform buffer: (channels, samples)
        self._waveform: np.ndarray = np.zeros((channels, 0))
        self._waveform_timestamps: np.ndarray = np.array([])
        self._last_timestamp: float = 0.0

    def update(self, output: EngineOutput) -> None:
        """Update state with a new pipeline output.

        Args:
            output: EngineOutput from pipeline.process_window().
        """
        with self._lock:
            self._last_timestamp = time.time()

            # Update focus
            self._focus = {
                "score": output.focus.score,
                "quality": round(output.focus.quality, 2),
                "state": output.focus.state,
                "reasons": output.focus.reasons,
            }

            # Update features
            gbp = output.features.global_band_powers
            self._features = {
                "globalBandPowers": {
                    "delta": round(gbp.delta, 2),
                    "theta": round(gbp.theta, 2),
                    "alpha": round(gbp.alpha, 2),
                    "beta": round(gbp.beta, 2),
                    "gamma": round(gbp.gamma, 2),
                },
                "thetaBetaRatio": round(output.features.theta_beta_ratio, 3),
                "alphaBetaRatio": round(output.features.alpha_beta_ratio, 3),
                "artifactRatio": round(output.features.artifact_ratio, 3),
            }

            # Update rolling waveform
            new_data = output.window.data  # (channels, samples)
            self._waveform = np.concatenate([self._waveform, new_data], axis=1)

            # Trim to waveform_seconds
            if self._waveform.shape[1] > self._waveform_samples:
                self._waveform = self._waveform[:, -self._waveform_samples:]

            # Update timestamps
            if output.window.start_time is not None:
                n_new = new_data.shape[1]
                new_ts = np.arange(n_new) / self._sample_rate + output.window.start_time
                self._waveform_timestamps = np.concatenate([self._waveform_timestamps, new_ts])
                if len(self._waveform_timestamps) > self._waveform_samples:
                    self._waveform_timestamps = self._waveform_timestamps[-self._waveform_samples:]

    def set_device_status(
        self,
        connected: bool,
        stream_name: str = "",
        sample_rate: float = 250.0,
        channels: int = 16,
    ) -> None:
        """Update device connection status."""
        with self._lock:
            self._device = {
                "connected": connected,
                "streamName": stream_name,
                "sampleRate": sample_rate,
                "channels": channels,
            }

    def get_state(self) -> dict:
        """Return the complete dashboard state dict.

        Thread-safe: returns a snapshot of the current state.
        """
        with self._lock:
            return {
                "timestamp": self._last_timestamp,
                "device": dict(self._device),
                "focus": dict(self._focus),
                "features": {
                    "globalBandPowers": dict(self._features["globalBandPowers"]),
                    "thetaBetaRatio": self._features["thetaBetaRatio"],
                    "alphaBetaRatio": self._features["alphaBetaRatio"],
                    "artifactRatio": self._features["artifactRatio"],
                },
                "eeg": {
                    "channels": self._channels,
                    "sampleRate": self._sample_rate,
                    "samples": self._waveform.tolist(),
                    "timestamps": self._waveform_timestamps.tolist(),
                },
            }
```

- [ ] **Step 5: 运行测试确认通过**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest ear_eeg_sound_lab.tests.test_state_provider -v
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add ear_eeg_sound_lab/src/web_app/__init__.py ear_eeg_sound_lab/src/web_app/state_provider.py ear_eeg_sound_lab/tests/test_state_provider.py
git commit -m "feat(web_app): add dashboard state provider"
```

---

### Task 2: server.py — HTTP + WebSocket 服务

**Files:**
- Create: `ear_eeg_sound_lab/src/web_app/server.py`

参考: `upper_machine/eeg_viewer/main.py` 的 WebSocket 实现模式

- [ ] **Step 1: 实现 server.py**

```python
"""Realtime EEG server — HTTP + WebSocket + processing main loop.

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
from ear_eeg_sound_lab.src.web_app.state_provider import DashboardStateProvider

STATIC_DIR = Path(__file__).with_name("static").resolve()


def _websocket_frame(payload: bytes) -> bytes:
    """Encode a payload as a WebSocket text frame (server → client)."""
    if len(payload) < 126:
        return struct.pack("!BB", 0x81, len(payload)) + payload
    if len(payload) <= 0xFFFF:
        return struct.pack("!BBH", 0x81, 126, len(payload)) + payload
    return struct.pack("!BBQ", 0x81, 127, len(payload)) + payload


class RealtimeHandler(BaseHTTPRequestHandler):
    """HTTP request handler with WebSocket upgrade support."""

    state_provider: DashboardStateProvider
    ws_clients: list[Any] = []
    ws_lock = threading.Lock()

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

        if self.path == "/" or self.path == "/index.html":
            self._serve_file(STATIC_DIR / "index.html", "text/html")
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

        # Register this client
        with self.ws_lock:
            self.ws_clients.append(self.wfile)

        try:
            while True:
                state = self.state_provider.get_state()
                payload = json.dumps(state, separators=(",", ":")).encode("utf-8")
                self.wfile.write(_websocket_frame(payload))
                self.wfile.flush()
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with self.ws_lock:
                if self.wfile in self.ws_clients:
                    self.ws_clients.remove(self.wfile)


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
        push_interval: WebSocket push interval in seconds.
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
        push_interval: float = 0.1,
    ) -> None:
        self.host = host
        self.port = port
        self.stream_name = stream_name
        self.stream_type = stream_type
        self.channels = channels
        self.sample_rate = sample_rate
        self.window_seconds = window_seconds
        self.step_seconds = step_seconds
        self.push_interval = push_interval

        self.state_provider = DashboardStateProvider(
            waveform_seconds=window_seconds,
            channels=channels,
            sample_rate=sample_rate,
        )
        self._stop_event = threading.Event()

    def run(self) -> None:
        """Start the server: LSL connection + HTTP/WS service + processing loop."""
        # Set state provider on handler class
        RealtimeHandler.state_provider = self.state_provider

        # Start HTTP server in a thread
        httpd = ThreadingHTTPServer((self.host, self.port), RealtimeHandler)
        http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        http_thread.start()
        print(f"[server] HTTP/WS listening on http://{self.host}:{self.port}")

        # Connect to LSL
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

            # Pull chunk
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

            # Process windows
            window = buffer.pop_next_window(
                window_seconds=self.window_seconds,
                step_seconds=self.step_seconds,
            )
            if window is not None:
                try:
                    output = process_window(window)
                    self.state_provider.update(output)
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
```

- [ ] **Step 2: 验证 server 可导入**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -c "from ear_eeg_sound_lab.src.web_app.server import RealtimeServer; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 验证 CLI help**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m ear_eeg_sound_lab.src.web_app.server --help
```

Expected: 显示 argparse help

- [ ] **Step 4: Commit**

```bash
git add ear_eeg_sound_lab/src/web_app/server.py
git commit -m "feat(web_app): add realtime server with HTTP + WebSocket"
```

---

### Task 3: static/index.html — 最小浏览器 UI

**Files:**
- Create: `ear_eeg_sound_lab/src/web_app/static/index.html`

- [ ] **Step 1: 创建 static 目录和 index.html**

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>earEEG Realtime</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, system-ui, sans-serif; background: #1a1a2e; color: #eee; }
.header { display: flex; justify-content: space-between; padding: 12px 20px; background: #16213e; }
.status { display: flex; gap: 16px; align-items: center; }
.badge { padding: 4px 10px; border-radius: 12px; font-size: 13px; }
.badge.ok { background: #0f3d0f; color: #4caf50; }
.badge.err { background: #3d0f0f; color: #f44336; }
.main { display: grid; grid-template-columns: 1fr 280px; gap: 16px; padding: 16px; height: calc(100vh - 56px); }
.panel { background: #16213e; border-radius: 8px; padding: 16px; }
.panel h3 { font-size: 14px; color: #aaa; margin-bottom: 12px; }
canvas { width: 100%; background: #0a0a1a; border-radius: 4px; }
.focus-score { font-size: 64px; font-weight: bold; text-align: center; }
.focus-state { text-align: center; font-size: 18px; margin: 8px 0; }
.reasons { font-size: 12px; color: #aaa; }
.reasons li { margin: 4px 0; }
.bars { display: flex; gap: 8px; align-items: flex-end; height: 120px; }
.bar { flex: 1; background: #4caf50; border-radius: 2px 2px 0 0; transition: height 0.2s; }
.bar-label { font-size: 11px; text-align: center; color: #aaa; margin-top: 4px; }
.ratios { font-size: 13px; color: #aaa; margin-top: 12px; }
.ratios div { margin: 4px 0; }
</style>
</head>
<body>
<div class="header">
  <div class="status">
    <span>earEEG Realtime</span>
    <span id="conn-badge" class="badge err">disconnected</span>
    <span id="device-badge" class="badge err">no device</span>
  </div>
  <div class="status">
    <span id="fps">0 fps</span>
  </div>
</div>
<div class="main">
  <div class="panel">
    <h3>EEG Waveform (16 channels)</h3>
    <canvas id="eeg-canvas" height="400"></canvas>
  </div>
  <div style="display:flex;flex-direction:column;gap:16px;">
    <div class="panel">
      <h3>Focus</h3>
      <div id="focus-score" class="focus-score">--</div>
      <div id="focus-state" class="focus-state">unknown</div>
      <ul id="focus-reasons" class="reasons"></ul>
    </div>
    <div class="panel">
      <h3>Band Powers</h3>
      <div id="bars" class="bars">
        <div><div class="bar" id="bar-delta" style="height:0"></div><div class="bar-label">δ</div></div>
        <div><div class="bar" id="bar-theta" style="height:0"></div><div class="bar-label">θ</div></div>
        <div><div class="bar" id="bar-alpha" style="height:0"></div><div class="bar-label">α</div></div>
        <div><div class="bar" id="bar-beta" style="height:0"></div><div class="bar-label">β</div></div>
        <div><div class="bar" id="bar-gamma" style="height:0"></div><div class="bar-label">γ</div></div>
      </div>
      <div class="ratios">
        <div>θ/β: <span id="tbr">--</span></div>
        <div>α/β: <span id="abr">--</span></div>
        <div>Quality: <span id="quality">--</span></div>
      </div>
    </div>
  </div>
</div>
<script>
const canvas = document.getElementById('eeg-canvas');
const ctx = canvas.getContext('2d');
let ws, msgCount = 0, lastFpsTime = Date.now();

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => {
    document.getElementById('conn-badge').className = 'badge ok';
    document.getElementById('conn-badge').textContent = 'connected';
  };
  ws.onclose = () => {
    document.getElementById('conn-badge').className = 'badge err';
    document.getElementById('conn-badge').textContent = 'disconnected';
    setTimeout(connect, 2000);
  };
  ws.onmessage = (e) => {
    const state = JSON.parse(e.data);
    update(state);
  };
}

function update(state) {
  msgCount++;
  const now = Date.now();
  if (now - lastFpsTime > 1000) {
    document.getElementById('fps').textContent = msgCount + ' fps';
    msgCount = 0;
    lastFpsTime = now;
  }

  // Device
  const dev = state.device;
  const devBadge = document.getElementById('device-badge');
  devBadge.className = dev.connected ? 'badge ok' : 'badge err';
  devBadge.textContent = dev.connected ? dev.streamName : 'no device';

  // Focus
  document.getElementById('focus-score').textContent = state.focus.score;
  document.getElementById('focus-state').textContent = state.focus.state;
  const ul = document.getElementById('focus-reasons');
  ul.innerHTML = state.focus.reasons.map(r => `<li>${r}</li>`).join('');

  // Quality
  document.getElementById('quality').textContent = (state.focus.quality * 100).toFixed(0) + '%';

  // Band powers
  const bp = state.features.globalBandPowers;
  const maxBp = Math.max(bp.delta, bp.theta, bp.alpha, bp.beta, bp.gamma, 1);
  ['delta','theta','alpha','beta','gamma'].forEach(b => {
    document.getElementById('bar-' + b).style.height = (bp[b] / maxBp * 100) + 'px';
  });
  document.getElementById('tbr').textContent = state.features.thetaBetaRatio.toFixed(2);
  document.getElementById('abr').textContent = state.features.alphaBetaRatio.toFixed(2);

  // Waveform
  drawWaveform(state.eeg);
}

function drawWaveform(eeg) {
  if (!eeg.samples || eeg.samples.length === 0) return;
  canvas.width = canvas.offsetWidth;
  canvas.height = canvas.offsetHeight;
  const w = canvas.width, h = canvas.height;
  const ch = eeg.channels;
  const rowH = h / ch;

  ctx.clearRect(0, 0, w, h);
  for (let c = 0; c < ch; c++) {
    const data = eeg.samples[c];
    if (!data || data.length === 0) continue;
    const y0 = c * rowH + rowH / 2;

    // Auto-scale per channel
    let min = Infinity, max = -Infinity;
    for (let i = 0; i < data.length; i++) {
      if (data[i] < min) min = data[i];
      if (data[i] > max) max = data[i];
    }
    const range = max - min || 1;

    ctx.strokeStyle = `hsl(${(c * 360 / ch) % 360}, 70%, 60%)`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < data.length; i++) {
      const x = (i / data.length) * w;
      const y = y0 - ((data[i] - min) / range - 0.5) * rowH * 0.8;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Channel label
    ctx.fillStyle = '#666';
    ctx.font = '10px sans-serif';
    ctx.fillText('Ch' + (c + 1), 4, c * rowH + 12);
  }
}

connect();
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add ear_eeg_sound_lab/src/web_app/static/index.html
git commit -m "feat(web_app): add minimal browser UI with waveform, focus, bands"
```

---

### Task 4: 端到端验证

- [ ] **Step 1: 运行全量测试**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m unittest discover -s ear_eeg_sound_lab/tests -p "test_*.py" -v
```

Expected: All tests pass.

- [ ] **Step 2: 验证 CLI 可启动**

Run:
```powershell
cd E:\yuan_space\10_projects\earEEG
python -m ear_eeg_sound_lab.src.web_app.server --help
```

Expected: 显示帮助信息。

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: realtime runner M2 complete"
```

---

## 联调步骤（手动验证）

```powershell
# 终端 1：模拟设备
python -m ear_eeg_sound_lab.src.simulated_device --auto-start --eeg-profile focused

# 终端 2：lsl_proxy
uv run --project upper_machine python -m upper_machine.lsl_proxy.main --host 127.0.0.1 --port 8889 --lsl --start

# 终端 3：实时引擎
python -m ear_eeg_sound_lab.src.web_app.server --port 8765

# 浏览器打开 http://127.0.0.1:8765
```

## 总结

| Task | 模块 | 测试 |
|------|------|------|
| 1 | state_provider.py | test_state_provider.py |
| 2 | server.py | CLI 验证 |
| 3 | static/index.html | 手动验证 |
| 4 | 端到端验证 | 全量测试 |
