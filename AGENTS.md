# earEEG

Firmware for an ESP32-S3 head-mounted EEG/audio/IMU data acquisition prototype.

## Project layout

```
earEEG/              # repo root (this file + design.md)
  earEEG/            # PlatformIO project root
    ...
  upper_machine/     # PC-side Python software
    lsl_proxy/       # TCP → parse → LSL outlet bridge (唯一TCP入口)
    recorder/        # LSL inlet → CSV/WAV file storage
    calibration/     # LSL inlet → FFT → calibration report
    common/          # shared protocol parsing (mirrors protocol.h)
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

## Hardware

| Module   | Interface | GPIO | Notes                      |
|----------|-----------|-----------------|----------------------------|
| PCM5102  | I2S0 TX   | 1/2/4           | BCLK=1, LRCLK=2, DIN=4     |
| INMP441  | I2S1 RX   | 7/8/9           | SCK=7, WS=8, SD=9          |
| BNO085   | I2C       | 5/6             | internal pullups on board  |
| OpenBCI  | UART1     | 17/18           | TX=17, RX=18, 115200 baud  |

GPIO3 is a strapping pin, leave unused. GPIO43/44 are reserved for the board's UART0 debug bridge.

## Architecture

- **Core 1**: real-time I/O — I2S RX task (16 kHz mono → mic ring buf), I2S TX task (44.1 kHz stereo ← downlink ring buf), IMU poll task (250 Hz, SHTP over I2C).
- **Core 0**: network + data — Wi-Fi STA, TCP server (recv dispatch + CMD handler), UART EEG parser, data packer (250 Hz, TYPE=0x01 frames → TCP send).
- All inter-core data uses PSRAM-backed SPSC ring buffers (`ring_buf.h`).
- Microsecond timestamps (`esp_timer_get_time()`) assigned by reader at 4 ms tick boundary, not in ISR.

## Init order (from main.c)

`ring_buf_create()` → peripheral init → `wifi_sta_init()` (blocks 15s) → start Core-1 I/O tasks → `tcp_server_start()` (blocks for client) → `data_packer_start()` → OpenBCI start command. If any step fails, `app_main` returns immediately.

## Style & gotchas

- C, ESP-IDF 6.0 framework (not Arduino).
- Every `.c` file that uses FreeRTOS types **must** `#include "freertos/FreeRTOS.h"` before any other FreeRTOS headers. Missing this is the #1 compilation failure (triggers cascade of `task.h` errors).
- `esp_cpu_get_cycle_count()` is in `esp_cpu.h`.
- `esp_timer_get_time()` is in `esp_timer.h`.
- `GPIO_NUM_x` enums come from `soc/gpio_num.h` (already included by `earEEG_config.h` — just `#include "earEEG_config.h"` when you need them).
- `htons` / `ntohs` need `<arpa/inet.h>`.
- `fcntl` needs `<fcntl.h>`.
- CRC-16-IBM parameter: poly 0x8005, init 0xFFFF, no final XOR (MODBUS style).
- Wi-Fi credentials default to `earEEG` / `password123`; set via menuconfig → `Component config → Wi-Fi` → add `CONFIG_WIFI_SSID` and `CONFIG_WIFI_PASSWORD` in sdkconfig.
- PSRAM is **enabled** in sdkconfig (Octal mode, 80 MHz). Ring buffers try `MALLOC_CAP_SPIRAM` first, fall back to DRAM.
- BNO085 I2C address is 0x4A; SHTP protocol uses channel 2 for sensor reports. Enable rotation vector, accelerometer, and gyroscope reports at 250 Hz.
- TCP wire format: SYNC `EE 01`, TYPE byte, LEN (big-endian), u64 timestamp (little-endian), payload, CRC-16 (little-endian). See `protocol.h` and §4 of `design.md`.

## Design doc reference

`design.md` at the repo root is the canonical specification. This hardware/architecture summary is derived from it.
