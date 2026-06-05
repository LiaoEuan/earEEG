"""Pure impedance math and OpenBCI command construction helpers."""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

import numpy as np


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
