"""Publish a synthetic 16-channel EEG stream for viewer testing."""

from __future__ import annotations

import argparse
import math
import signal
import time

import numpy as np
from pylsl import StreamInfo, StreamOutlet, local_clock


STREAM_NAME = "earEEG_EEG"
CHANNELS = 16
SAMPLE_RATE = 250


def create_outlet() -> StreamOutlet:
    info = StreamInfo(
        STREAM_NAME,
        "EEG",
        CHANNELS,
        float(SAMPLE_RATE),
        "float32",
        source_id="earEEG_simulator",
    )
    desc = info.desc()
    desc.append_child_value("manufacturer", "earEEG")
    desc.append_child_value("model", "synthetic EEG generator")
    channels = desc.append_child("channels")
    for index in range(CHANNELS):
        channel = channels.append_child("channel")
        channel.append_child_value("label", f"CH{index + 1:02d}")
        channel.append_child_value("unit", "raw ADC")
        channel.append_child_value("type", "EEG")
    return StreamOutlet(info, chunk_size=0, max_buffered=60)


def generate_chunk(start_sample: int, count: int, amplitude: float,
                   noise: float, artifact: bool,
                   rng: np.random.Generator) -> np.ndarray:
    sample_indexes = np.arange(start_sample, start_sample + count)
    t = sample_indexes / SAMPLE_RATE
    chunk = np.zeros((count, CHANNELS), dtype=np.float32)

    for channel in range(CHANNELS):
        frequency = 8.0 + channel * 0.55
        phase = channel * math.pi / 8.0
        alpha = amplitude * np.sin(2.0 * math.pi * frequency * t + phase)
        drift = amplitude * 0.18 * np.sin(2.0 * math.pi * 0.25 * t + phase)
        channel_noise = rng.normal(0.0, noise, size=count)
        chunk[:, channel] = alpha + drift + channel_noise + channel * amplitude * 0.08

    if artifact:
        artifact_phase = np.mod(t, 5.0)
        mask = artifact_phase < 0.12
        if np.any(mask):
            pulse = amplitude * 2.5 * (1.0 - artifact_phase[mask] / 0.12)
            chunk[mask] += pulse[:, None]

    return chunk


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish synthetic 16-channel EEG data to LSL"
    )
    parser.add_argument("--amplitude", type=float, default=120000.0,
                        help="base signal amplitude in raw ADC units")
    parser.add_argument("--noise", type=float, default=12000.0,
                        help="noise standard deviation in raw ADC units")
    parser.add_argument("--chunk-ms", type=float, default=40.0,
                        help="LSL push interval in milliseconds")
    parser.add_argument("--artifact", action="store_true",
                        help="inject a short common-mode pulse every 5 seconds")
    parser.add_argument("--seed", type=int, default=42,
                        help="random seed for reproducible noise")
    args = parser.parse_args()

    chunk_samples = max(1, round(SAMPLE_RATE * args.chunk_ms / 1000.0))
    rng = np.random.default_rng(args.seed)
    outlet = create_outlet()
    running = True

    def stop(*_args) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    print(f"[sim] publishing {STREAM_NAME}: {CHANNELS}ch @ {SAMPLE_RATE} Hz")
    print(f"[sim] chunk={chunk_samples} samples, amplitude={args.amplitude:g}, "
          f"noise={args.noise:g}, artifact={'on' if args.artifact else 'off'}")
    print("[sim] press Ctrl+C to stop")

    start_time = local_clock()
    next_sample = 0
    last_stats = start_time

    while running:
        now = local_clock()
        due_samples = int((now - start_time) * SAMPLE_RATE) - next_sample
        if due_samples < chunk_samples:
            time.sleep(min(0.005, (chunk_samples - due_samples) / SAMPLE_RATE))
            continue

        # Catch up in bounded chunks if the process was briefly descheduled.
        count = min(due_samples, chunk_samples * 4)
        chunk = generate_chunk(next_sample, count, args.amplitude, args.noise,
                               args.artifact, rng)
        last_timestamp = start_time + (next_sample + count - 1) / SAMPLE_RATE
        outlet.push_chunk(chunk.tolist(), last_timestamp)
        next_sample += count

        if now - last_stats >= 5.0:
            print(f"[sim] sent {next_sample} samples "
                  f"({next_sample / (now - start_time):.1f} Hz)", flush=True)
            last_stats = now

    print(f"\n[sim] stopped after {next_sample} samples")


if __name__ == "__main__":
    main()
