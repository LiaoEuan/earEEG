"""
play_audio.py — Stream WAV to ESP32 for I2S playback with real-time pacing.

Usage:
    python play_audio.py sample-15s.wav [--host 192.168.4.1] [--port 8888]
    python play_audio.py sample-15s.wav --start-acq   # also enable uplink sensor data
"""

import argparse
import ctypes
import socket
import struct
import sys
import threading
import time
import wave

from upper_machine.common.protocol import (
    build_frame, TYPE_DNLINK_AUDIO, TYPE_COMMAND, CMD_START_ACQ,
)


def send_audio_file(host: str, port: int, wav_path: str, *,
                    start_acq: bool = False, prefill_ms: int = 500,
                    batch_ms: int = 50):
    """Connect to ESP32 and stream a WAV file with real-time pacing."""

    # ── Raise Windows timer resolution to 1 ms for accurate pacing ──
    # On Windows the default sleep granularity is ~15.6 ms, which causes
    # bursty delivery and underruns. timeBeginPeriod(1) brings it to ~1 ms.
    _winmm = None
    if sys.platform == 'win32':
        try:
            _winmm = ctypes.windll.winmm
            _winmm.timeBeginPeriod(1)
        except Exception:
            _winmm = None

    # ── Open WAV ────────────────────────────────────────────────
    try:
        wf = wave.open(wav_path, 'rb')
    except FileNotFoundError:
        print(f"[play] file not found: {wav_path}")
        sys.exit(1)

    nchannels = wf.getnchannels()
    sampwidth = wf.getsampwidth()
    framerate = wf.getframerate()
    total_frames = wf.getnframes()
    duration = total_frames / framerate
    print(f"[play] {wav_path}: {nchannels}ch, {sampwidth}B, {framerate}Hz, {duration:.1f}s")

    if framerate != 44100:
        print(f"[play] WARNING: expected 44100Hz, got {framerate}Hz")
    if nchannels not in (1, 2):
        print(f"[play] unsupported channel count: {nchannels} (expected mono or stereo)")
        wf.close()
        return
    if sampwidth not in (2, 3, 4):
        print(f"[play] unsupported sample width: {sampwidth}B (expected 16/24/32-bit PCM)")
        wf.close()
        return

    # ── Connect ─────────────────────────────────────────────────
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    try:
        sock.connect((host, port))
    except (OSError, TimeoutError) as e:
        print(f"[play] connect failed: {e}")
        wf.close()
        sys.exit(1)

    # Disable Nagle for low-latency small-packet sends
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.settimeout(1.0)
    print(f"[play] connected to {host}:{port}")

    # Keep reading ACK and optional sensor uplink frames so the ESP32 send path
    # cannot stall while this process is primarily streaming audio downlink.
    stop_reader = threading.Event()

    def drain_incoming():
        while not stop_reader.is_set():
            try:
                if not sock.recv(4096):
                    break
            except socket.timeout:
                continue
            except OSError:
                break

    reader_thread = threading.Thread(target=drain_incoming, daemon=True)
    reader_thread.start()

    # ── Optional: start acquisition (enables uplink sensor data) ──
    if start_acq:
        frame = build_frame(TYPE_COMMAND, 0, bytes([CMD_START_ACQ]))
        sock.sendall(frame)
        time.sleep(0.2)
        print("[play] CMD_START_ACQ sent (uplink sensor data enabled)")
    else:
        print("[play] audio-only mode (no uplink sensor data)")

    # ── Pacing setup ────────────────────────────────────────────
    # 10ms chunks ≈ 441 samples @ 44100Hz
    samples_per_chunk = int(framerate * 0.010)
    chunk_sec = samples_per_chunk / framerate  # exact seconds per chunk
    total_chunks = (total_frames + samples_per_chunk - 1) // samples_per_chunk

    # Pre-fill: burst the first N chunks to build ring-buffer headroom
    prefill_count = max(1, int(prefill_ms / 1000 / chunk_sec))

    # Keep bursts short while remaining above typical Windows timer granularity.
    batch_size = max(1, int(batch_ms / 1000 / chunk_sec))

    print(f"[play] chunk={samples_per_chunk}smp ({chunk_sec*1000:.0f}ms)  "
          f"prefill={prefill_count} ({prefill_count*chunk_sec*1000:.0f}ms)  "
          f"batch={batch_size}")

    # ── Helpers ─────────────────────────────────────────────────
    def convert_chunk(raw_pcm: bytes) -> bytes:
        """Ensure 16-bit stereo PCM regardless of input format."""
        r = raw_pcm
        # Width → 16-bit (keep upper bits for quality)
        if sampwidth == 3:
            out = bytearray()
            for i in range(0, len(r), 3):
                out.extend(r[i+1:i+3])  # upper 16 of LE 24-bit
            r = bytes(out)
        elif sampwidth == 4:
            out = bytearray()
            for i in range(0, len(r), 4):
                out.extend(r[i+2:i+4])  # upper 16 of LE 32-bit
            r = bytes(out)
        # Mono → stereo (duplicate L→R)
        if nchannels == 1:
            out = bytearray()
            for i in range(0, len(r), 2):
                s = r[i:i+2]
                out.extend(s)
                out.extend(s)
            r = bytes(out)
        return r

    # ── Stream ──────────────────────────────────────────────────
    total_bytes = 0
    chunks_sent = 0
    pace_origin = None  # set once pre-fill completes
    t0 = time.time()
    eof = False

    try:
        while not eof:
            # ── Send a batch of chunks ──
            for _ in range(batch_size):
                raw = wf.readframes(samples_per_chunk)
                if len(raw) == 0:
                    eof = True
                    break
                raw = convert_chunk(raw)
                if len(raw) % 4 != 0:
                    raise ValueError("converted PCM is not aligned to stereo 16-bit samples")
                payload = struct.pack('B', 0x02) + raw
                frame = build_frame(TYPE_DNLINK_AUDIO, 0, payload)
                sock.sendall(frame)
                total_bytes += len(raw)
                chunks_sent += 1

            # ── Pacing (after pre-fill) ──
            if chunks_sent >= prefill_count:
                if pace_origin is None:
                    pace_origin = time.monotonic()
                    print("[play] pre-fill done, real-time streaming...")
                # Drift-correcting sleep: keeps cumulative rate at 1× real-time
                target = pace_origin + (chunks_sent - prefill_count) * chunk_sec
                delta = target - time.monotonic()
                if delta > 0.001:
                    time.sleep(delta)

            # ── Progress every ~2s ──
            if chunks_sent > 0 and chunks_sent % (batch_size * 40) == 0:
                el = time.time() - t0
                pct = chunks_sent / total_chunks * 100
                rate_kbs = total_bytes / el / 1024
                print(f"[play] {el:5.1f}s  {pct:3.0f}%  {rate_kbs:.0f} KB/s")

    except KeyboardInterrupt:
        print("\n[play] interrupted")
    except OSError as e:
        print(f"[play] send error: {e}")
    except ValueError as e:
        print(f"[play] invalid audio data: {e}")
    finally:
        elapsed = time.time() - t0
        kbps = total_bytes * 8 / 1000 / max(elapsed, 0.001)
        print(f"[play] done: {total_bytes/1024:.0f} KB in {elapsed:.1f}s ({kbps:.0f} kbps)")
        wf.close()
        stop_reader.set()
        sock.close()
        reader_thread.join(timeout=1.0)
        if _winmm is not None:
            _winmm.timeEndPeriod(1)


def main():
    parser = argparse.ArgumentParser(description="Stream WAV to earEEG ESP32")
    parser.add_argument("wav", help="WAV file (44100Hz stereo 16-bit preferred)")
    parser.add_argument("--host", default="192.168.4.1")
    parser.add_argument("--port", type=int, default=8888)
    parser.add_argument("--start-acq", action="store_true",
                        help="enable uplink sensor data (default: audio-only)")
    parser.add_argument("--prefill", type=int, default=500,
                        help="pre-fill buffer duration in ms (default: 500)")
    parser.add_argument("--batch-ms", type=int, default=50,
                        help="audio sent per pacing cycle in ms (default: 50)")

    args = parser.parse_args()
    send_audio_file(args.host, args.port, args.wav,
                    start_acq=args.start_acq, prefill_ms=args.prefill,
                    batch_ms=args.batch_ms)


if __name__ == "__main__":
    main()
