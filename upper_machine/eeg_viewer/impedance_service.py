"""LSL-backed impedance measurement for the browser viewer."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict
from urllib import error, request

import numpy as np

from upper_machine.impedance import (
    DEFAULT_CURRENT_NA,
    DEFAULT_GAIN,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SERIES_RESISTANCE_OHM,
    DEFAULT_TEST_FREQUENCY,
    ImpedanceResult,
    calculate_impedance,
    classify_impedance,
    openbci_impedance_command,
    parse_channels,
)

from .eeg_buffer import EEGBuffer


class ImpedanceService:
    def __init__(self, eeg_buffer: EEGBuffer, proxy_url: str):
        self._eeg_buffer = eeg_buffer
        self._proxy_url = proxy_url.rstrip("/")
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._running = False
        self._current_channel = 0
        self._last_error = ""
        self._results: list[ImpedanceResult] = []

    def start(self, channels: str = "1-8", duration: float = 3.0) -> dict:
        with self._lock:
            if self._running:
                return {"ok": False, "error": "impedance measurement is already running"}
            try:
                channel_list = parse_channels(channels)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

            self._stop.clear()
            self._running = True
            self._current_channel = 0
            self._last_error = ""
            self._results = []
            self._thread = threading.Thread(
                target=self._run,
                args=(channel_list, max(0.5, float(duration))),
                daemon=True,
            )
            self._thread.start()
        return {"ok": True, "status": self.status()}

    def stop(self) -> dict:
        self._stop.set()
        self._proxy_post("/impedance/stop")
        with self._lock:
            self._running = False
            self._current_channel = 0
        return {"ok": True, "status": self.status()}

    def status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "currentChannel": self._current_channel,
                "lastError": self._last_error,
                "results": [asdict(result) for result in self._results],
            }

    def _run(self, channels: list[int], duration: float) -> None:
        try:
            self._proxy_post("/acquisition/start")
            time.sleep(0.5)
            sample_count = max(2, round(duration * DEFAULT_SAMPLE_RATE))

            for channel in channels:
                if self._stop.is_set():
                    break
                self._set_current_channel(channel)
                enable = openbci_impedance_command(channel, True)
                disable = openbci_impedance_command(channel, False)
                self._proxy_post("/impedance/control", {"command": enable})
                try:
                    time.sleep(0.5)
                    samples = self._collect_channel(channel, sample_count,
                                                    timeout=duration + 2.0)
                    rms_uv, total_kohm, electrode_kohm = calculate_impedance(
                        samples,
                        sample_rate=DEFAULT_SAMPLE_RATE,
                        frequency=DEFAULT_TEST_FREQUENCY,
                        gain=DEFAULT_GAIN,
                        current_na=DEFAULT_CURRENT_NA,
                        series_resistance_ohm=DEFAULT_SERIES_RESISTANCE_OHM,
                    )
                    quality = classify_impedance(electrode_kohm, 10.0, 20.0)
                    self._append_result(ImpedanceResult(
                        channel=channel,
                        sample_count=len(samples),
                        frequency_hz=DEFAULT_TEST_FREQUENCY,
                        rms_uv=rms_uv,
                        total_kohm=total_kohm,
                        electrode_kohm=electrode_kohm,
                        quality=quality,
                    ))
                finally:
                    self._proxy_post("/impedance/control", {"command": disable})
                    time.sleep(0.1)
        except Exception as exc:
            self._set_error(str(exc))
        finally:
            self._proxy_post("/impedance/stop")
            with self._lock:
                self._running = False
                self._current_channel = 0

    def _collect_channel(self, channel: int, count: int, timeout: float) -> np.ndarray:
        _, start_total = self._eeg_buffer.snapshot(0.1)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._stop.is_set():
            samples, total = self._eeg_buffer.snapshot_since(start_total)
            if total - start_total >= count and len(samples) >= count:
                values = samples[-count:, channel - 1]
                return np.asarray(values, dtype=np.float64)
            time.sleep(0.05)
        raise RuntimeError(f"timed out waiting for channel {channel} impedance samples")

    def _proxy_post(self, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body or {}, separators=(",", ":")).encode("utf-8")
        req = request.Request(f"{self._proxy_url}{path}", data=data, method="POST",
                              headers={"Content-Type": "application/json"})
        try:
            with request.urlopen(req, timeout=2.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {"error": str(exc)}
            raise RuntimeError(payload.get("error", str(exc))) from exc
        except OSError as exc:
            raise RuntimeError(str(exc)) from exc

    def _set_current_channel(self, channel: int) -> None:
        with self._lock:
            self._current_channel = channel

    def _append_result(self, result: ImpedanceResult) -> None:
        with self._lock:
            self._results.append(result)

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message
