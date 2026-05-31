#pragma once

#include <stdint.h>

/* ── Frame constants (§4.2) ─────────────────────────────────────── */

#define PROTO_SYNC_0    0xEE
#define PROTO_SYNC_1    0x01

#define PROTO_TYPE_SENSOR      0x01
#define PROTO_TYPE_DNLINK_AUDIO 0x02
#define PROTO_TYPE_COMMAND     0x03
#define PROTO_TYPE_ACK         0x04

/* ── Command IDs (§4.6) ─────────────────────────────────────────── */

#define CMD_START_ACQ       0x01
#define CMD_STOP_ACQ        0x02
#define CMD_SET_EEG_PARAMS  0x03

#define CMD_IMPEDANCE_CTRL  0x10
#define CMD_IMPEDANCE_STOP  0x11

/* ── Frame header (before payload) ──────────────────────────────── */

#define PROTO_HEADER_SIZE   13    // SYNC(2) + TYPE(1) + LEN(2) + TIMESTAMP(8)
#define PROTO_CRC_SIZE      2
#define PROTO_FRAME_OVERHEAD (PROTO_HEADER_SIZE + PROTO_CRC_SIZE)

#pragma pack(push, 1)
typedef struct {
    uint8_t  sync0;
    uint8_t  sync1;
    uint8_t  type;
    uint16_t len;          // big-endian payload length
    uint64_t timestamp;    // little-endian microsecond timestamp
} proto_header_t;

typedef struct {
    uint16_t seq_id;
    uint8_t  eeg_active_channels;
    uint8_t  reserved;
    // followed by: eeg_data[EEG_CHANNELS_MAX * 3]
    //              mic samples header
    //              imu payload
} sensor_payload_t;

typedef struct {
    uint8_t  channels;
    // followed by: interleaved PCM L/R (4 bytes per stereo sample)
} dwnlink_audio_t;

typedef struct {
    uint8_t  cmd_id;
    // followed by: cmd_data
} command_payload_t;

typedef struct {
    uint8_t  cmd_id;
    uint8_t  status;       // 0 = success
} ack_payload_t;
#pragma pack(pop)
