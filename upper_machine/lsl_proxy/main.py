"""
lsl_proxy — CLI entry point.

Modes:
  --cmd "..."   Send a single command to ESP32 and exit.
  --lsl         Continuous streaming: TCP → parse → 3 LSL outlets.
  (default)     TCP → parse → print to console.
"""

import argparse
import signal
import sys
import time

from .tcp_client import TCPClient
from upper_machine.common.protocol import SensorData


def main():
    parser = argparse.ArgumentParser(description="earEEG LSL Proxy")
    parser.add_argument("--host", default="192.168.4.1",
                        help="ESP32 IP address (default: 192.168.4.1)")
    parser.add_argument("--port", type=int, default=8888,
                        help="TCP port (default: 8888)")
    parser.add_argument("--cmd", default=None,
                        help="send a single raw ASCII command (as CMD=0x10 payload) and exit")
    parser.add_argument("--no-start", action="store_true",
                        help="do not auto-send CMD_START_ACQ on connect")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="print every frame to stdout")
    parser.add_argument("--stats", "-s", action="store_true",
                        help="print periodic statistics")
    parser.add_argument("--lsl", action="store_true",
                        help="push data to LSL outlets (requires pylsl)")
    parser.add_argument("--play", metavar="WAV",
                        help="stream a WAV file while receiving sensor data")
    parser.add_argument("--prefill", type=int, default=500,
                        help="downlink pre-fill duration in ms (default: 500)")
    parser.add_argument("--batch-ms", type=int, default=50,
                        help="downlink audio sent per pacing cycle in ms (default: 50)")
    args = parser.parse_args()

    # ── Single command mode ────────────────────────────────────

    if args.cmd is not None:
        _oneshot_cmd(args.host, args.port, args.cmd)
        return

    # ── LSL outlet manager (optional) ──────────────────────────

    lsl_manager = None
    if args.lsl:
        try:
            from .lsl_outlet import LSLOutletManager
            lsl_manager = LSLOutletManager()
        except Exception as e:
            print(f"[proxy] LSL init failed: {e}")
            sys.exit(1)

    # ── TCP client ─────────────────────────────────────────────

    client = TCPClient(args.host, args.port)
    audio_player = None

    # Statistics
    frame_count = 0
    last_seq = -1
    lost_packets = 0
    start_time = 0.0
    last_stats_time = 0.0
    origin_set = False

    def on_sensor(s: SensorData):
        nonlocal frame_count, last_seq, lost_packets, origin_set
        frame_count += 1

        # Seq ID continuity check
        if last_seq >= 0:
            expected = (last_seq + 1) & 0xFFFF
            if s.seq_id != expected:
                lost_packets += (s.seq_id - expected) & 0xFFFF
        last_seq = s.seq_id

        # Console output
        if args.verbose:
            _print_sensor(s)

        # LSL push
        if lsl_manager:
            if not origin_set:
                lsl_manager.set_origin(s.timestamp)
                origin_set = True

            try:
                lsl_manager.push_eeg(s.eeg_raw, s.active_channels, s.timestamp)
                lsl_manager.push_audio(s.mic_samples, s.timestamp)
                lsl_manager.push_imu(s.quat_w, s.quat_x, s.quat_y, s.quat_z, s.timestamp)
            except Exception as e:
                print(f"[proxy] LSL push failed: {e}", flush=True)

    client.on_sensor_data(on_sensor)

    # ── Graceful shutdown ──────────────────────────────────────

    running = [True]

    def _shutdown(sig=None, frame=None):
        if running[0]:
            print("\n[proxy] shutting down...")
            client.stop_acquisition()
            running[0] = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # ── Connect ─────────────────────────────────────────────────

    print(f"[proxy] connecting to {args.host}:{args.port} ...")
    if not client.connect():
        print("[proxy] connection failed")
        sys.exit(1)

    if not args.no_start:
        time.sleep(0.3)
        print("[proxy] sending CMD_START_ACQ ...")
        client.start_acquisition()

    if args.play:
        from .audio_player import AudioPlayer
        audio_player = AudioPlayer(client, args.play, prefill_ms=args.prefill,
                                   batch_ms=args.batch_ms)
        audio_player.start()

    start_time = time.time()
    last_stats_time = start_time

    # ── Main loop ──────────────────────────────────────────────

    try:
        while running[0] and client.connected:
            time.sleep(1.0)

            if args.stats:
                now = time.time()
                elapsed = now - start_time
                fps = frame_count / elapsed if elapsed > 0 else 0
                loss = (lost_packets / (frame_count + lost_packets) * 100
                        if (frame_count + lost_packets) > 0 else 0)
                print(f"[stats] {elapsed:.0f}s | frames={frame_count} ({fps:.0f}/s) | "
                      f"lost={lost_packets} ({loss:.1f}%)", flush=True)

    except KeyboardInterrupt:
        pass
    finally:
        _shutdown()
        if audio_player:
            audio_player.stop()
        client.disconnect()
        if lsl_manager:
            lsl_manager.close()
        elapsed = time.time() - start_time
        print(f"[proxy] session end. {frame_count} frames in {elapsed:.1f}s "
              f"({frame_count / elapsed:.1f} fps), lost={lost_packets}")


def _oneshot_cmd(host: str, port: int, cmd_str: str):
    from upper_machine.common.protocol import build_frame, TYPE_COMMAND

    client = TCPClient(host, port)
    print(f"[cmd] connecting to {host}:{port} ...")
    if not client.connect():
        print("[cmd] connection failed")
        sys.exit(1)

    print(f"[cmd] sending: {cmd_str}")
    payload = bytes([0x10]) + cmd_str.encode("ascii")
    frame = build_frame(TYPE_COMMAND, 0, payload)
    client.send_raw(frame)

    time.sleep(0.5)
    client.disconnect()
    print("[cmd] done")


def _print_sensor(s: SensorData):
    """Pretty-print one sensor frame to console."""
    eeg_vals = []
    for ch in range(min(s.active_channels, 8)):
        off = ch * 3
        raw24 = int.from_bytes(s.eeg_raw[off:off + 3], byteorder='big', signed=True)
        eeg_vals.append(f"{raw24:7d}")
    eeg_str = " ".join(eeg_vals) if eeg_vals else "--"

    mic_vals = []
    for i in range(0, min(len(s.mic_samples), 16), 2):
        val = int.from_bytes(s.mic_samples[i:i + 2], byteorder='little', signed=True)
        mic_vals.append(f"{val:6d}")
    mic_str = " ".join(mic_vals) if mic_vals else "--"

    print(f"[SENSOR] seq={s.seq_id:4d} ts={s.timestamp:13d} | "
          f"EEG[{s.active_channels:2d}ch] {eeg_str} | "
          f"MIC {mic_str} | "
          f"QUAT w={s.quat_w:.3f} x={s.quat_x:.3f} y={s.quat_y:.3f} z={s.quat_z:.3f}")


if __name__ == "__main__":
    main()
