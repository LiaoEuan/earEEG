# earEEG

Firmware for an ESP32-S3 head-mounted EEG/audio/IMU data acquisition prototype.

## Project layout

```
earEEG/                     # repo root (this file + design.md)
  earEEG/                   # PlatformIO project root
    src/
      main.c                # init sequence, global ring buffers, status loop
      i2s_audio.c           # I2S0 TX (PCM5102) + I2S1 RX (INMP441) tasks
      tcp_stream.c          # TCP server, frame parser, command dispatch
      data_packer.c         # TYPE=0x01 sensor frame builder (250 Hz)
      uart_eeg.c            # OpenBCI UART parser task
      i2c_imu.c             # BNO085 SHTP driver & poll task (disabled)
      wifi_ap.c             # Wi-Fi soft-AP (current mode)
      wifi_sta.c            # Wi-Fi station (legacy, not in build)
      protocol.c            # wire frame builder + CRC
      ring_buf.c            # SPSC ring buffer (PSRAM-backed)
      crc16.c               # CRC-16-IBM (MODBUS style)
    include/                # matching headers for each .c above
    platformio.ini          # board: seeed_xiao_esp32s3, framework: espidf
    sdkconfig.seeed_xiao_esp32s3  # ESP-IDF 6.0 config (PSRAM Octal 80 MHz)
    CMakeLists.txt
  upper_machine/            # PC-side Python software
    common/
      protocol.py           # frame parser, CRC, sensor unpack (mirrors protocol.h)
    lsl_proxy/              # TCP → parse → LSL outlet bridge (唯一TCP入口)
      main.py               # CLI: --lsl, --cmd, --verbose, --stats
      tcp_client.py         # TCP connection mgmt, recv loop, command send
      lsl_outlet.py         # 3 LSL outlets (EEG/Audio/IMU)
    recorder/               # LSL inlet → CSV/WAV file storage
      main.py, lsl_inlet.py, storage.py
    calibration/            # LSL inlet → FFT → calibration report (WIP)
    play_audio.py           # stream WAV → ESP32 I2S with real-time pacing
    test_protocol.py        # unit tests for protocol parsing
```

Actual project root for PlatformIO is `earEEG/earEEG/`.

## Commands

```sh
pio run -d earEEG/earEEG                          # build
pio run -d earEEG/earEEG -t upload                # flash
pio run -d earEEG/earEEG -t monitor               # serial (USB-C/JTAG)
pio run -d earEEG/earEEG -t menuconfig            # configure (Wi-Fi SSID, etc.)
pio run -d earEEG/earEEG -t clean
pio test -d earEEG/earEEG
```

SDK config file is `sdkconfig.seeed_xiao_esp32s3` (not plain `sdkconfig`).

## Hardware

| Module   | Interface | GPIO | Notes                      |
|----------|-----------|------|----------------------------|
| PCM5102  | I2S0 TX   | 1/2/4 | BCLK=1, LRCLK=2, DIN=4 |
| INMP441  | I2S1 RX   | 7/8/9 | SCK=7, WS=8, SD=9 |
| BNO085   | I2C       | 5/6   | internal pullups on board; **currently disabled** |
| OpenBCI  | UART1     | 17/18 | TX=17, RX=18, 115200 baud |

GPIO3 is a strapping pin, leave unused. GPIO43/44 are reserved for the board's UART0 debug bridge.

**Pin assignments are defined in `earEEG_config.h` and have not changed from the original specification.**

## Architecture

- **Core 1** (高实时采集核): I2S RX task (16 kHz mono → mic ring buf), I2S TX task (44.1 kHz stereo ← downlink ring buf), EEG parser task (started on acquisition start), data packer task (250 Hz TYPE=0x01 frames → TCP send).
- **Core 0** (通信与协议核): Wi-Fi soft-AP stack, TCP receive task (frame parser state machine, command dispatch, downlink audio routing to ring buffer).
- All inter-core data uses PSRAM-backed SPSC ring buffers (`ring_buf.h`), allocated with `MALLOC_CAP_SPIRAM` first, falling back to DRAM.
- Timestamps (`esp_timer_get_time()`) are assigned by the data packer at packet build time, not in ISRs.

### Current operational status

- **Audio playback (I2S TX)**: actively being debugged. Known issues — underrun recovery logic in place (300ms start watermark, ~6ms recovery watermark). Downlink ring buffer is 4 MB (increased from original 256 KB design). `play_audio.py` provides PC-side WAV streaming with drift-corrected pacing and a TCP drain thread.
- **IMU (BNO085)**: disabled via `#if 0` in `main.c`. Init code and SHTP driver are complete but polling task is untested. Do **not** test or enable IMU functionality.

## Init order (from main.c)

`ring_buf_create()` → `wifi_ap_init()` (non-blocking, AP starts immediately) → delay 500ms → `i2s_audio_init()` → `i2s_audio_start()` (pins I2S RX/TX tasks to Core 1) → `tcp_server_start()` (blocks for first client, then spawns recv task on Core 0) → `uart_eeg_init()` (UART driver install, parser task NOT started yet) → `data_packer_start()` (pins packer task to Core 1) → main status loop.

The EEG parser task is started lazily — only when `CMD_START_ACQ` arrives. This avoids Core 0 contention between LWIP and UART interrupts while no client is connected.

If any step fails after `wifi_ap_init()`, `app_main` enters an infinite delay loop (device stays alive for debugging via serial).

IMU init and start are `#if 0`'d out entirely.

## Wi-Fi

- **Current mode**: Soft-AP. SSID `earEEG`, password `password123`, IP `192.168.4.1`, port `8888`.
- **Legacy mode**: `wifi_sta.c/h` exist but are not compiled into the current build. STA mode blocks up to 15s waiting for DHCP; AP mode is instant.
- AP credentials are hardcoded in `earEEG_config.h` (macros `AP_SSID`, `AP_PASSWORD`, `AP_MAX_CONNECTIONS`, `AP_CHANNEL`).

## TCP protocol

Wire format: SYNC `EE 01`, TYPE byte, LEN (big-endian), u64 timestamp (little-endian), payload, CRC-16 (little-endian). See `protocol.h` and §4 of `design.md`.

| TYPE | Name | Direction | Handled by |
|------|------|-----------|------------|
| `0x01` | SENSOR_DATA | ESP32 → PC | `data_packer.c` builds; `lsl_proxy` parses |
| `0x02` | DOWNLINK_AUDIO | PC → ESP32 | `tcp_stream.c` writes to downlink ring buf |
| `0x03` | COMMAND | PC → ESP32 | `tcp_stream.c` dispatches |
| `0x04` | ACK | ESP32 → PC | `tcp_stream.c` sends after command handling |

### Commands implemented

| CMD | Function | Behavior |
|-----|----------|----------|
| `0x01` | START_ACQ | Resets EEG+mic ring buffers, sends `b` to OpenBCI, starts EEG parser task on Core 1, sets `g_acq_running=true`, returns ACK |
| `0x02` | STOP_ACQ | Sends `s` to OpenBCI, sets `g_acq_running=false`, returns ACK |
| `0x10` | IMPEDANCE_CTRL | Transparently forwards payload bytes to OpenBCI UART (e.g. `z410Z`), returns ACK |
| `0x11` | IMPEDANCE_STOP | Sends `z100Zz200Z...z800Z` to OpenBCI (disables all impedance channels), returns ACK |

## Style & gotchas

- C, ESP-IDF 6.0 framework (not Arduino).
- Every `.c` file that uses FreeRTOS types **must** `#include "freertos/FreeRTOS.h"` before any other FreeRTOS headers. Missing this is the #1 compilation failure (triggers cascade of `task.h` errors).
- `esp_cpu_get_cycle_count()` is in `esp_cpu.h`.
- `esp_timer_get_time()` is in `esp_timer.h`.
- `GPIO_NUM_x` enums come from `soc/gpio_num.h` (already included by `earEEG_config.h` — just `#include "earEEG_config.h"` when you need them).
- `htons` / `ntohs` need `<arpa/inet.h>`.
- `fcntl` needs `<fcntl.h>`.
- CRC-16-IBM parameter: poly 0x8005, init 0xFFFF, no final XOR (MODBUS style).
- PSRAM is **enabled** in sdkconfig (Octal mode, 80 MHz). Ring buffers try `MALLOC_CAP_SPIRAM` first, fall back to DRAM.
- BNO085 I2C address is 0x4A; SHTP protocol uses channel 2 for sensor reports. Driver code is complete but disabled.
- TCP client socket is set to `O_NONBLOCK`. `setsockopt(TCP_NODELAY)` crashes on this lwIP build — throughput managed by PC-side pacing instead.
- OpenBCI streams continuously on power-up. EEG parser task starts only on acquisition start to avoid Core 0 UART+LWIP interrupt contention.

## Ring buffer allocation

| Buffer | Size | Purpose |
|--------|------|---------|
| `g_rb_eeg` | 24 KB | EEG frames (8/16ch × 3B @ 250Hz) |
| `g_rb_mic` | 64 KB | MIC PCM (16kHz mono 16-bit) |
| `g_rb_dnlink` | 4 MB | Downlink audio (44.1kHz stereo 16-bit) |
| `g_rb_imu` | 4 KB | IMU samples (allocated but unused) |

The 4 MB downlink buffer is significantly larger than the design spec (256 KB) to absorb Wi-Fi jitter during audio playback debugging.

## Design doc reference

`design.md` at the repo root is the canonical specification. This hardware/architecture summary is derived from it, updated to reflect current implementation state as of 2026-05-31.
