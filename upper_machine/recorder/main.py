import argparse
import signal
import sys
import time
from datetime import datetime

from .lsl_inlet import LSLInletManager
from .storage import StorageWriter


def main():
    parser = argparse.ArgumentParser(description="earEEG Recorder")
    parser.add_argument("--duration", "-d", type=float, default=0,
                        help="recording duration in seconds (0 = until Ctrl+C)")
    parser.add_argument("--output", "-o", default="./data",
                        help="output directory (default: ./data)")
    parser.add_argument("--tag", default="",
                        help="session tag for directory naming")
    parser.add_argument("--flush-interval", type=float, default=1.0,
                        help="file flush interval in seconds (default: 1.0)")
    args = parser.parse_args()

    print("[rec] resolving LSL streams ...")
    try:
        inlet = LSLInletManager()
    except RuntimeError as e:
        print(f"[rec] {e}")
        sys.exit(1)

    writer = StorageWriter(args.output, args.tag)
    writer.open_csv("earEEG_EEG", ["timestamp"] + [f"ch{i}" for i in range(24)])
    writer.open_csv("earEEG_IMU", ["timestamp", "qw", "qx", "qy", "qz",
                                    "gx", "gy", "gz", "ax", "ay", "az"])
    writer.open_wav()

    print(f"[rec] session: {writer.session_id}")
    print(f"[rec] output:  {writer.session_dir}")

    running = [True]
    start_time = time.time()

    def _shutdown(sig=None, frame=None):
        if running[0]:
            print("\n[rec] stopping ...")
            running[0] = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    last_flush = time.time()

    try:
        while running[0]:
            if args.duration > 0 and (time.time() - start_time) >= args.duration:
                print("[rec] duration reached")
                break

            data = inlet.pull_blocking(timeout=0.5)

            if "earEEG_EEG" in data:
                eeg = data["earEEG_EEG"]
                for row in eeg:
                    writer.write_csv_row("earEEG_EEG",
                                         [datetime.utcnow().isoformat()] + row.tolist())

            if "earEEG_IMU" in data:
                imu = data["earEEG_IMU"]
                for row in imu:
                    writer.write_csv_row("earEEG_IMU",
                                         [datetime.utcnow().isoformat()] + row.tolist())

            if "earEEG_Audio" in data:
                writer.write_wav_chunk(data["earEEG_Audio"].flatten())

            now = time.time()
            if now - last_flush >= args.flush_interval:
                elapsed = now - start_time
                eeg_n = inlet.sample_count("earEEG_EEG")
                print(f"[rec] {elapsed:.0f}s | eeg={eeg_n} samples", flush=True)
                last_flush = now

    except KeyboardInterrupt:
        pass
    finally:
        _shutdown()
        writer.close()
        inlet.close()
        elapsed = time.time() - start_time
        print(f"[rec] done. {elapsed:.0f}s saved to {writer.session_dir}")


if __name__ == "__main__":
    main()
