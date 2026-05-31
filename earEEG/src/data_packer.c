#include "data_packer.h"
#include "earEEG_config.h"
#include "protocol.h"
#include "ring_buf.h"
#include "i2c_imu.h"
#include "tcp_stream.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

static const char *TAG = "packer";

// Acquisition enabled flag (set by command handler via TCP)
volatile bool g_acq_running = false;

// Ring buffers (set by main.c)
extern ring_buf_t *g_rb_eeg;
extern ring_buf_t *g_rb_mic;

static TaskHandle_t s_packer_task = NULL;
static volatile bool s_running    = false;

// Packer task: build & send TYPE=0x01 frames at 250 Hz
static void packer_task_fn(void *arg)
{
    uint16_t seq_id = 0;
    uint8_t  frame_buf[512];  // generous size for one frame
    TickType_t last_wake = xTaskGetTickCount();

    while (s_running) {
        if (!g_acq_running || !tcp_is_connected()) {
            vTaskDelay(pdMS_TO_TICKS(PACKET_INTERVAL_MS));
            last_wake = xTaskGetTickCount();
            continue;
        }

        uint64_t ts = esp_timer_get_time();

        // ── Build payload first (we need to know LEN) ──

#define PAYLOAD_OFFSET PROTO_HEADER_SIZE

        // SEQ ID
        uint8_t *seq_p = (uint8_t *)&seq_id;
        frame_buf[PAYLOAD_OFFSET + 0] = seq_p[0];
        frame_buf[PAYLOAD_OFFSET + 1] = seq_p[1];

        // EEG HEADER + DATA
        frame_buf[PAYLOAD_OFFSET + 2] = 0; // active channels (filled below)
        frame_buf[PAYLOAD_OFFSET + 3] = 0; // reserved

        // Zero-fill EEG data (72 bytes)
        memset(frame_buf + PAYLOAD_OFFSET + 4, 0, 72);

    // Try to read latest EEG frame from ring buffer
    uint16_t eeg_ch = 0;
    uint16_t eeg_sz = 0;
    if (g_rb_eeg && ring_buf_avail(g_rb_eeg) >= 4) {
        uint8_t peek[4];
        ring_buf_peek(g_rb_eeg, peek, 4);
        eeg_ch = peek[0] | (uint16_t)(peek[1] << 8);
        eeg_sz = peek[2] | (uint16_t)(peek[3] << 8);

        size_t entry_sz = 4 + eeg_sz;
        if (ring_buf_avail(g_rb_eeg) >= entry_sz && eeg_sz <= 48) {
            uint8_t entry[52]; // max: 4 header + 48 eeg (16ch × 3B)
            ring_buf_read(g_rb_eeg, entry, entry_sz);
            eeg_ch = entry[0] | (uint16_t)(entry[1] << 8);
            eeg_sz = entry[2] | (uint16_t)(entry[3] << 8);
            memcpy(frame_buf + PAYLOAD_OFFSET + 4, entry + 4, eeg_sz);
        }
    }
        frame_buf[PAYLOAD_OFFSET + 2] = (uint8_t)eeg_ch; // active channels

        // MIC PAYLOAD
        size_t mic_off = PAYLOAD_OFFSET + 2 + 2 + 72;
        // sample count
        uint16_t mic_cnt = MIC_SAMPLES_PER_PACKET;
        frame_buf[mic_off + 0] = mic_cnt & 0xFF;
        frame_buf[mic_off + 1] = (mic_cnt >> 8) & 0xFF;
        // PCM data
        size_t mic_bytes = mic_cnt * sizeof(int16_t);
        memset(frame_buf + mic_off + 2, 0, mic_bytes);
        if (g_rb_mic) {
            ring_buf_read(g_rb_mic, frame_buf + mic_off + 2, mic_bytes);
        }

        // IMU PAYLOAD
        size_t imu_off = mic_off + 2 + mic_bytes;
        memset(frame_buf + imu_off, 0, IMU_PAYLOAD_BYTES);
        if (g_imu_latest.valid) {
            memcpy(frame_buf + imu_off + 0,  &g_imu_latest.quat_w, 4);
            memcpy(frame_buf + imu_off + 4,  &g_imu_latest.quat_x, 4);
            memcpy(frame_buf + imu_off + 8,  &g_imu_latest.quat_y, 4);
            memcpy(frame_buf + imu_off + 12, &g_imu_latest.quat_z, 4);
        }

        // ── Build header ──
        uint16_t payload_len = SENSOR_PAYLOAD_SIZE;
        size_t frame_size = 0;

        // TIMESTAMP (little-endian u64)
        if (!proto_build_frame(PROTO_TYPE_SENSOR, ts,
                               frame_buf + PAYLOAD_OFFSET, payload_len,
                               frame_buf, sizeof(frame_buf), &frame_size)) {
            ESP_LOGE(TAG, "failed to build sensor frame");
            continue;
        }

        // ── CRC16 over header + payload ──

        // ── Send ──
        tcp_send(frame_buf, frame_size);

        seq_id++;

        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(PACKET_INTERVAL_MS));
    }

    vTaskDelete(NULL);
}

bool data_packer_init(void)
{
    ESP_LOGI(TAG, "data packer init OK");
    return true;
}

void data_packer_start(void)
{
    if (s_running) return;
    s_running = true;
    xTaskCreatePinnedToCore(packer_task_fn, "packer", STACK_PACKER_SENDER,
                            NULL, PRIO_PACKER_SENDER, &s_packer_task, 1);
    ESP_LOGI(TAG, "packer task started");
}

void data_packer_stop(void)
{
    s_running = false;
    if (s_packer_task) { vTaskDelete(s_packer_task); s_packer_task = NULL; }
    ESP_LOGI(TAG, "packer task stopped");
}
