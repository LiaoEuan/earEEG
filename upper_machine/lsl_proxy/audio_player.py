"""Background WAV streaming over an existing earEEG TCP connection."""

import threading
import time
import wave
from pathlib import Path

from .tcp_client import TCPClient


class AudioPlayer:
    """Stream a WAV file without taking ownership of the TCP connection."""

    def __init__(self, client: TCPClient, wav_path: str, *,
                 prefill_ms: int = 500, batch_ms: int = 50):
        self._client = client
        self._wav_path = wav_path
        self._prefill_ms = prefill_ms
        self._batch_ms = batch_ms
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._lock = threading.Lock()
        self._finished = False
        self._last_error = ""

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def pause(self):
        self._pause.set()

    def resume(self):
        self._pause.clear()

    @property
    def wav_path(self) -> str:
        return self._wav_path

    @property
    def file_name(self) -> str:
        return Path(self._wav_path).name

    @property
    def running(self) -> bool:
        return self._thread.is_alive() and not self._finished

    @property
    def paused(self) -> bool:
        return self._pause.is_set() and self.running

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def _run(self):
        try:
            with wave.open(self._wav_path, "rb") as wf:
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                sample_rate = wf.getframerate()
                total_frames = wf.getnframes()

                if channels not in (1, 2):
                    raise ValueError(f"unsupported channel count: {channels}")
                if sample_width not in (2, 3, 4):
                    raise ValueError(f"unsupported sample width: {sample_width}B")
                if sample_rate != 44100:
                    print(f"[play] WARNING: expected 44100Hz, got {sample_rate}Hz")

                chunk_frames = max(1, int(sample_rate * 0.010))
                chunk_sec = chunk_frames / sample_rate
                prefill_count = max(1, int(self._prefill_ms / 1000 / chunk_sec))
                batch_size = max(1, int(self._batch_ms / 1000 / chunk_sec))
                duration = total_frames / sample_rate
                print(f"[play] {self._wav_path}: {duration:.1f}s, "
                      f"prefill={prefill_count * chunk_sec * 1000:.0f}ms")

                chunks_sent = 0
                pace_origin = None
                while not self._stop.is_set() and self._client.connected:
                    if self._pause.is_set():
                        while self._pause.is_set() and not self._stop.is_set():
                            self._stop.wait(0.05)
                        if pace_origin is not None:
                            paced_chunks = max(0, chunks_sent - prefill_count)
                            pace_origin = time.monotonic() - paced_chunks * chunk_sec
                        continue

                    eof = False
                    for _ in range(batch_size):
                        if self._stop.is_set() or self._pause.is_set():
                            break
                        raw = wf.readframes(chunk_frames)
                        if not raw:
                            eof = True
                            break
                        pcm = _to_stereo_16bit(raw, channels, sample_width)
                        if not self._client.send_audio(pcm):
                            return
                        chunks_sent += 1

                    if eof:
                        print("[play] playback finished")
                        self._finished = True
                        return

                    if chunks_sent >= prefill_count:
                        if pace_origin is None:
                            pace_origin = time.monotonic()
                            print("[play] pre-fill done, real-time streaming...")
                        target = pace_origin + (chunks_sent - prefill_count) * chunk_sec
                        delay = target - time.monotonic()
                        if delay > 0.001:
                            self._stop.wait(delay)
        except (OSError, ValueError, wave.Error) as e:
            with self._lock:
                self._last_error = str(e)
            print(f"[play] playback failed: {e}")
        finally:
            self._finished = True


def _to_stereo_16bit(raw: bytes, channels: int, sample_width: int) -> bytes:
    """Convert PCM samples to the ESP32 playback format."""
    if sample_width == 3:
        raw = b"".join(raw[i + 1:i + 3] for i in range(0, len(raw), 3))
    elif sample_width == 4:
        raw = b"".join(raw[i + 2:i + 4] for i in range(0, len(raw), 4))

    if channels == 1:
        raw = b"".join(raw[i:i + 2] * 2 for i in range(0, len(raw), 2))
    return raw
