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

from .control_server import ControlServer, ProxyController, ProxyStatus
from .tcp_client import TCPClient
from upper_machine.common.eeg_units import (
    decode_openbci_eeg_counts,
    openbci_counts_to_uv,
)
from upper_machine.common.protocol import SensorData


def main():
    parser = argparse.ArgumentParser(description="earEEG LSL Proxy")
    parser.add_argument("--host", default="192.168.4.1",
                        help="ESP32 IP address (default: 192.168.4.1)")
    parser.add_argument("--port", type=int, default=8888,
                        help="TCP port (default: 8888)")
    parser.add_argument("--cmd", default=None,
                        help="send a single raw ASCII command (as CMD=0x10 payload) and exit")
    parser.add_argument("--start", action="store_true",
                        help="send CMD_START_ACQ after connecting (default: wait for control)")
    parser.add_argument("--no-start", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="print every frame to stdout")
    parser.add_argument("--eeg-unit", choices=["uv", "counts", "both"], default="uv",
                        help="EEG unit for verbose TCP debug output (default: uv)")
    parser.add_argument("--eeg-gain", type=float, default=24.0,
                        help="OpenBCI/ADS1299 EEG gain for count-to-uV conversion (default: 24)")
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
    parser.add_argument("--control-host", default="127.0.0.1",
                        help="local control API host (default: 127.0.0.1)")
    parser.add_argument("--control-port", type=int, default=8787,
                        help="local control API port (default: 8787)")
    parser.add_argument("--no-control", action="store_true",
                        help="disable the local HTTP control API")
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
    control_server = None

    # Statistics
    frame_count = 0
    last_seq = -1
    lost_packets = 0
    start_time = 0.0
    origin_set = False

    def _current_status() -> ProxyStatus:
        elapsed = max(time.time() - start_time, 0.001)
        loss = (lost_packets / (frame_count + lost_packets) * 100
                if (frame_count + lost_packets) > 0 else 0)
        fps = frame_count / elapsed if start_time > 0 else 0
        return ProxyStatus(
            connected=client.connected,
            acquiring=controller.acquiring,
            frame_count=frame_count,
            lost_packets=lost_packets,
            fps=fps,
            loss_percent=loss,
            last_error=controller.last_error,
        )

    controller = ProxyController(client, _current_status)

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
            _print_sensor(s, eeg_unit=args.eeg_unit, eeg_gain=args.eeg_gain)

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
            if controller.acquiring and client.connected:
                controller.stop_acquisition()
            running[0] = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # ── Connect ─────────────────────────────────────────────────

    print(f"[proxy] connecting to {args.host}:{args.port} ...")
    if not client.connect():
        print("[proxy] connection failed")
        sys.exit(1)

    if not args.no_control:
        control_server = ControlServer(args.control_host, args.control_port, controller)
        try:
            control_server.start()
        except OSError as e:
            print(f"[control] failed to start: {e}")
            client.disconnect()
            sys.exit(1)

    if args.start and not args.no_start:
        time.sleep(0.3)
        print("[proxy] sending CMD_START_ACQ ...")
        controller.start_acquisition()
    else:
        print("[proxy] acquisition is idle; use the control API or --start")

    if args.play:
        result = controller.play_audio(args.play, prefill_ms=args.prefill,
                                       batch_ms=args.batch_ms)
        if not result.get("ok"):
            print(f"[play] {result.get('error', 'failed to start playback')}")

    start_time = time.time()

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
        controller.stop_audio()
        if control_server:
            control_server.stop()
        controller.mark_disconnected()
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


def _print_sensor(s: SensorData, eeg_unit: str = "uv", eeg_gain: float = 24.0):
    """Pretty-print one sensor frame to console."""
    printed_channels = min(s.active_channels, 8)
    counts = decode_openbci_eeg_counts(s.eeg_raw, printed_channels)
    if eeg_unit == "counts":
        eeg_vals = [f"{raw24:7d}" for raw24 in counts]
        eeg_label = "counts"
    elif eeg_unit == "both":
        eeg_uv = openbci_counts_to_uv(counts, gain=eeg_gain)
        eeg_vals = [f"{raw24:7d}/{uv:8.2f}" for raw24, uv in zip(counts, eeg_uv)]
        eeg_label = "counts/uV"
    else:
        eeg_uv = openbci_counts_to_uv(counts, gain=eeg_gain)
        eeg_vals = [f"{uv:8.2f}" for uv in eeg_uv]
        eeg_label = "uV"
    eeg_str = " ".join(eeg_vals) if eeg_vals else "--"

    mic_vals = []
    for i in range(0, min(len(s.mic_samples), 16), 2):
        val = int.from_bytes(s.mic_samples[i:i + 2], byteorder='little', signed=True)
        mic_vals.append(f"{val:6d}")
    mic_str = " ".join(mic_vals) if mic_vals else "--"

    channel_label = (f"{s.active_channels:2d}ch" if printed_channels == s.active_channels
                     else f"{printed_channels}/{s.active_channels}ch")
    print(f"[SENSOR] seq={s.seq_id:4d} ts={s.timestamp:13d} | "
          f"EEG[{channel_label} {eeg_label}] {eeg_str} | "
          f"MIC {mic_str} | "
          f"QUAT w={s.quat_w:.3f} x={s.quat_x:.3f} y={s.quat_y:.3f} z={s.quat_z:.3f}")


if __name__ == "__main__":
    main()
