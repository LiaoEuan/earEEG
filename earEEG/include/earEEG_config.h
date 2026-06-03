#pragma once

#include <stdint.h>
#include "soc/gpio_num.h"

/* ── GPIO pin assignments (§2.3) ────────────────────────────────── */

// I2S0 TX -> WM8960 playback
#define PIN_I2S0_BCLK   GPIO_NUM_1
#define PIN_I2S0_LRCLK  GPIO_NUM_2
#define PIN_I2S0_DIN    GPIO_NUM_4

// I2S1 RX → INMP441
#define PIN_I2S1_BCLK   GPIO_NUM_7
#define PIN_I2S1_LRCLK  GPIO_NUM_8
#define PIN_I2S1_DOUT   GPIO_NUM_9

// I2C → BNO085
#define PIN_I2C_SDA      GPIO_NUM_5
#define PIN_I2C_SCL      GPIO_NUM_6

// UART → OpenBCI
#define PIN_UART_TX      GPIO_NUM_17
#define PIN_UART_RX      GPIO_NUM_18

/* ── Audio sample rates (§2.2) ──────────────────────────────────── */

#define SAMPLE_RATE_TX      44100   // WM8960 playback
#define SAMPLE_RATE_RX      16000   // INMP441 recording
#define AUDIO_BITS_PER_SAMPLE 16
#define TX_CHANNELS         2       // stereo
#define RX_CHANNELS         1       // mono (I2S frame still has 2 slots)

// Playback diagnostic modes:
//   0 = normal stereo
//   1 = duplicate left samples into the right I2S slot
//   2 = force the right I2S slot to silence
#define AUDIO_TX_DIAG_MODE 2

/* ── EEG ────────────────────────────────────────────────────────── */

#define EEG_SAMPLE_RATE     250     // Hz
#define EEG_CHANNELS_MAX    24      // max raw slots
#define EEG_BYTES_PER_SAMPLE 3      // 24-bit
#define EEG_FRAME_BYTES     (EEG_CHANNELS_MAX * EEG_BYTES_PER_SAMPLE)

// OpenBCI UART
#define OPENBCI_BAUDRATE    115200
#define OPENBCI_UART_NUM    UART_NUM_1

/* ── IMU (BNO085) ───────────────────────────────────────────────── */

#define IMU_POLL_RATE_HZ    250     // aligned to EEG packet rate
#define IMU_PAYLOAD_BYTES   38      // quat(16B) + reserved(22B)

/* ── Packet timing (§4.4) ───────────────────────────────────────── */

#define PACKET_INTERVAL_MS  4       // 250 Hz
#define MIC_SAMPLES_PER_PACKET 64   // 16000 / 250

// TYPE=0x01 payload size
#define SENSOR_PAYLOAD_SIZE \
    (2 + 2 + EEG_FRAME_BYTES + 2 + (MIC_SAMPLES_PER_PACKET * 2) + IMU_PAYLOAD_BYTES)

/* ── Ring buffer depths (PSRAM, §3.2) ───────────────────────────── */

#define RB_EEG_SIZE_BYTES   (24 * 1024)
#define RB_MIC_SIZE_BYTES   (64 * 1024)
#define RB_DNLINK_SIZE_BYTES (4 * 1024 * 1024)  /* 4 MB */
#define RB_IMU_SIZE_BYTES   (4 * 1024)

/* ── I2S DMA ────────────────────────────────────────────────────── */

#define I2S_DMA_BUF_COUNT_RX 4
#define I2S_DMA_BUF_COUNT_TX 8
#define I2S_DMA_BUF_LEN_RX   256   // stereo samples per DMA buffer (RX)
#define I2S_DMA_BUF_LEN_TX   256   // stereo samples per DMA buffer (TX)
#define DNLINK_START_WATERMARK_MS 300

/* ── Wi-Fi ───────────────────────────────────────────────────────── */

#define WIFI_SSID           CONFIG_WIFI_SSID
#define WIFI_PASSWORD       CONFIG_WIFI_PASSWORD

/* ── Wi-Fi AP mode ──────────────────────────────────────────── */
#define AP_SSID             "earEEG"
#define AP_PASSWORD         "password123"
#define AP_MAX_CONNECTIONS  4
#define AP_CHANNEL          1

/* ── TCP server ──────────────────────────────────────────────────── */

#define TCP_SERVER_PORT     8888
#define TCP_RECV_BUF_SIZE   16384
#define TCP_SEND_BUF_SIZE   8192

/* ── Task priorities & stacks ────────────────────────────────────── */

#define PRIO_EEG_PARSER     6
#define PRIO_IMU_POLL        5
#define PRIO_PACKER_SENDER   4
#define PRIO_TCP_RECV        3
#define PRIO_CMD_HANDLER     3
#define PRIO_I2S_RX          5
#define PRIO_I2S_TX          7

#define STACK_EEG_PARSER     4096
#define STACK_IMU_POLL        3072
#define STACK_PACKER_SENDER   4096
#define STACK_TCP_RECV        8192
#define STACK_CMD_HANDLER     3072
