"""Automated OpenBCI Cyton lead-off impedance measurement over earEEG TCP."""

import argparse
import json
import math
import sys
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from upper_machine.common.protocol import SensorData
from upper_machine.lsl_proxy.tcp_client import TCPClient


DEFAULT_SAMPLE_RATE = 250.0
DEFAULT_TEST_FREQUENCY = 31.25
DEFAULT_GAIN = 24.0
DEFAULT_CURRENT_NA = 6.0
DEFAULT_SERIES_RESISTANCE_OHM = 2200.0
CHANNEL_CODES = "12345678QWERTYUI"


@dataclass
class ImpedanceResult:
    channel: int
    sample_count: int
    frequency_hz: float
    rms_uv: float
    total_kohm: float
    electrode_kohm: float
    quality: str


class SensorCollector:
    """Thread-safe handoff from TCP receive callbacks to the measurement loop."""

    def __init__(self):
        self._condition = threading.Condition()
        self._samples: deque[SensorData] = deque()

    def add(self, sensor: SensorData):
        with self._condition:
            self._samples.append(sensor)
            self._condition.notify_all()

    def clear(self):
        with self._condition:
            self._samples.clear()

    def collect_channel(self, channel: int, count: int, timeout: float) -> np.ndarray:
        values = []
        deadline = time.monotonic() + timeout
        with self._condition:
            while len(values) < count:
                while self._samples and len(values) < count:
                    sensor = self._samples.popleft()
                    if sensor.active_channels < channel:
                        continue
                    offset = (channel - 1) * 3
                    raw = sensor.eeg_raw[offset:offset + 3]
                    if len(raw) == 3:
                        values.append(int.from_bytes(raw, byteorder="big", signed=True))

                if len(values) >= count:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)

        if len(values) < count:
            raise RuntimeError(
                f"timed out waiting for channel {channel}: got {len(values)}/{count} samples"
            )
        return np.asarray(values, dtype=np.float64)


def adc_volts_per_count(gain: float) -> float:
    """Return the Cyton ADS1299 ADC scale in volts per raw count."""
    if gain <= 0:
        raise ValueError("gain must be positive")
    return 4.5 / gain / ((1 << 23) - 1)


def tone_rms_counts(samples: np.ndarray, sample_rate: float, frequency: float) -> float:
    """Estimate a tone RMS amplitude with a Hann-windowed single-bin DFT."""
    values = np.asarray(samples, dtype=np.float64)
    if values.ndim != 1 or len(values) < 2:
        raise ValueError("at least two one-dimensional samples are required")
    if sample_rate <= 0 or frequency <= 0 or frequency >= sample_rate / 2:
        raise ValueError("frequency must be between zero and the Nyquist frequency")

    centered = values - np.mean(values)
    window = np.hanning(len(centered))
    phase = np.exp(-2j * np.pi * frequency * np.arange(len(centered)) / sample_rate)
    peak_counts = 2.0 * abs(np.sum(centered * window * phase)) / np.sum(window)
    return float(peak_counts / math.sqrt(2.0))


def calculate_impedance(
    samples: np.ndarray,
    sample_rate: float = DEFAULT_SAMPLE_RATE,
    frequency: float = DEFAULT_TEST_FREQUENCY,
    gain: float = DEFAULT_GAIN,
    current_na: float = DEFAULT_CURRENT_NA,
    series_resistance_ohm: float = DEFAULT_SERIES_RESISTANCE_OHM,
) -> tuple[float, float, float]:
    """Return tone RMS microvolts, total kOhm, and electrode-only kOhm."""
    if current_na <= 0:
        raise ValueError("current_na must be positive")
    if series_resistance_ohm < 0:
        raise ValueError("series resistance cannot be negative")

    rms_uv = tone_rms_counts(samples, sample_rate, frequency) * adc_volts_per_count(gain) * 1e6
    total_ohm = rms_uv * 1e-6 * math.sqrt(2.0) / (current_na * 1e-9)
    electrode_ohm = max(0.0, total_ohm - series_resistance_ohm)
    return rms_uv, total_ohm / 1000.0, electrode_ohm / 1000.0


def classify_impedance(electrode_kohm: float, good_kohm: float, ok_kohm: float) -> str:
    if electrode_kohm < good_kohm:
        return "good"
    if electrode_kohm < ok_kohm:
        return "acceptable"
    return "adjust-electrode"


def openbci_impedance_command(channel: int, enabled: bool) -> str:
    if channel < 1 or channel > len(CHANNEL_CODES):
        raise ValueError(f"channel must be between 1 and {len(CHANNEL_CODES)}")
    return f"z{CHANNEL_CODES[channel - 1]}{1 if enabled else 0}0Z"


def run_measurement(args: argparse.Namespace) -> list[ImpedanceResult]:
    collector = SensorCollector()
    client = TCPClient(args.host, args.port)
    client.on_sensor_data(collector.add)

    print(f"[impedance] connecting to {args.host}:{args.port} ...")
    if not client.connect():
        raise RuntimeError("device connection failed; stop lsl_proxy if it is already connected")

    sample_count = max(2, round(args.duration * args.sample_rate))
    results = []
    acquisition_started = False
    try:
        time.sleep(0.3)
        if not client.start_acquisition():
            raise RuntimeError("failed to send acquisition start command")
        acquisition_started = True
        print("[impedance] acquisition started")
        time.sleep(args.initial_wait)

        for channel in args.channels:
            enable = openbci_impedance_command(channel, True)
            disable = openbci_impedance_command(channel, False)
            print(f"[impedance] Ch{channel}: enabling ({enable})")
            if not client.set_impedance(enable):
                raise RuntimeError(f"failed to enable impedance test for channel {channel}")
            try:
                collector.clear()
                time.sleep(args.settle)
                collector.clear()
                samples = collector.collect_channel(
                    channel, sample_count, timeout=args.duration + args.timeout_margin
                )
                rms_uv, total_kohm, electrode_kohm = calculate_impedance(
                    samples,
                    sample_rate=args.sample_rate,
                    frequency=args.frequency,
                    gain=args.gain,
                    current_na=args.current_na,
                    series_resistance_ohm=args.series_resistance,
                )
                quality = classify_impedance(electrode_kohm, args.good_kohm, args.ok_kohm)
                result = ImpedanceResult(
                    channel=channel,
                    sample_count=len(samples),
                    frequency_hz=args.frequency,
                    rms_uv=rms_uv,
                    total_kohm=total_kohm,
                    electrode_kohm=electrode_kohm,
                    quality=quality,
                )
                results.append(result)
                print(
                    f"[impedance] Ch{channel}: {electrode_kohm:.2f} kOhm "
                    f"(total={total_kohm:.2f} kOhm, tone={rms_uv:.2f} uVrms) [{quality}]"
                )
            finally:
                client.set_impedance(disable)
                time.sleep(args.command_delay)
    finally:
        client.stop_impedance()
        if acquisition_started:
            client.stop_acquisition()
        time.sleep(args.command_delay)
        client.disconnect()

    return results


def parse_channels(value: str) -> list[int]:
    channels = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" in item:
            start_text, end_text = item.split("-", 1)
            channels.extend(range(int(start_text), int(end_text) + 1))
        else:
            channels.append(int(item))
    if not channels or any(channel < 1 or channel > len(CHANNEL_CODES) for channel in channels):
        raise argparse.ArgumentTypeError("channels must be a comma-separated subset of 1-16")
    return list(dict.fromkeys(channels))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Automatically measure OpenBCI electrode impedance through earEEG"
    )
    parser.add_argument("--host", default="192.168.4.1")
    parser.add_argument("--port", type=int, default=8888)
    parser.add_argument(
        "--channels",
        type=parse_channels,
        default=parse_channels("1-8"),
        help="channel list or range (default: 1-8)",
    )
    parser.add_argument("--duration", type=float, default=3.0, help="measurement seconds per channel")
    parser.add_argument("--settle", type=float, default=0.5, help="settling seconds after enabling")
    parser.add_argument("--initial-wait", type=float, default=0.5)
    parser.add_argument("--timeout-margin", type=float, default=2.0)
    parser.add_argument("--command-delay", type=float, default=0.1)
    parser.add_argument("--sample-rate", type=float, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument("--frequency", type=float, default=DEFAULT_TEST_FREQUENCY)
    parser.add_argument("--gain", type=float, default=DEFAULT_GAIN)
    parser.add_argument("--current-na", type=float, default=DEFAULT_CURRENT_NA)
    parser.add_argument(
        "--series-resistance",
        type=float,
        default=DEFAULT_SERIES_RESISTANCE_OHM,
        help="series resistor to subtract in ohms; use 0 to report total impedance only",
    )
    parser.add_argument("--good-kohm", type=float, default=10.0)
    parser.add_argument("--ok-kohm", type=float, default=20.0)
    parser.add_argument("--json", type=Path, help="optional JSON report path")
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    try:
        results = run_measurement(args)
    except (RuntimeError, ValueError, UnicodeEncodeError) as exc:
        print(f"[impedance] error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        args.json.write_text(
            json.dumps([asdict(result) for result in results], indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"[impedance] report written to {args.json}")


if __name__ == "__main__":
    main()
