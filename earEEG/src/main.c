#include <stdio.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_system.h"

#include "earEEG_config.h"
#include "ring_buf.h"
#include "i2s_audio.h"
#include "uart_eeg.h"
#include "i2c_imu.h"
#include "wifi_ap.h"
#include "tcp_stream.h"
#include "data_packer.h"

static const char *TAG = "main";

// Global ring buffer pointers (shared across modules)
ring_buf_t *g_rb_eeg    = NULL;
ring_buf_t *g_rb_mic    = NULL;
ring_buf_t *g_rb_dnlink = NULL;
ring_buf_t *g_rb_imu    = NULL;

void app_main(void)
{
    ESP_LOGI(TAG, "========== earEEG firmware starting ==========");

    // ── 1. Create ring buffers (PSRAM) ──
    ESP_LOGI(TAG, "allocating ring buffers...");

    g_rb_eeg    = ring_buf_create(RB_EEG_SIZE_BYTES);
    g_rb_mic    = ring_buf_create(RB_MIC_SIZE_BYTES);
    g_rb_dnlink = ring_buf_create(RB_DNLINK_SIZE_BYTES);
    g_rb_imu    = ring_buf_create(RB_IMU_SIZE_BYTES);

    if (!g_rb_eeg || !g_rb_mic || !g_rb_dnlink || !g_rb_imu) {
        ESP_LOGE(TAG, "ring buffer allocation failed — check PSRAM config");
        return;
    }
    ESP_LOGI(TAG, "ring buffers: eeg=%u mic=%u dnl=%u imu=%u bytes",
             RB_EEG_SIZE_BYTES, RB_MIC_SIZE_BYTES,
             RB_DNLINK_SIZE_BYTES, RB_IMU_SIZE_BYTES);

    // ── 2. Init Wi-Fi AP ──
    if (!wifi_ap_init()) {
        ESP_LOGE(TAG, "Wi-Fi AP init failed");
        return;
    }
    char *ip = wifi_ap_get_ip();
    ESP_LOGI(TAG, "AP ready at %s", ip ? ip : "192.168.4.1");
    free(ip);

    // Let Wi-Fi subsystem stabilize before touching peripherals
    vTaskDelay(pdMS_TO_TICKS(500));

    // ── 3. Init peripherals ──
    ESP_LOGI(TAG, "initializing peripherals...");

    if (!i2s_audio_init()) {
        ESP_LOGE(TAG, "I2S init failed");
        while (1) vTaskDelay(pdMS_TO_TICKS(5000));
    }

#if 0   // test IMU - init OK but polling task crashes
    if (!imu_bno085_init()) {
        ESP_LOGE(TAG, "IMU init failed");
        while (1) vTaskDelay(pdMS_TO_TICKS(5000));
    }
#endif

    // ── 4. Start background I/O (Core 1) ──
    i2s_audio_start();
#if 0   // IMU start
    imu_bno085_start();
#endif

    // ── 5. Start TCP server (Core 0) ──
    int client_fd = tcp_server_start();
    if (client_fd < 0) {
        ESP_LOGE(TAG, "TCP server failed");
        while (1) vTaskDelay(pdMS_TO_TICKS(5000));
    }
    vTaskDelay(pdMS_TO_TICKS(500));  // let TCP/ARP stabilize

    // ── 5b. Init UART after TCP is stable ──
    if (!uart_eeg_init()) {
        ESP_LOGE(TAG, "UART init failed");
        while (1) vTaskDelay(pdMS_TO_TICKS(5000));
    }

    // ── 6. Start data packer (Core 0) ──
    data_packer_start();

    // ── 7. Main loop — monitor status ──
    ESP_LOGI(TAG, "system running. waiting for commands...");
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(5000));

        // Periodic status output
        size_t eeg_avail  = g_rb_eeg    ? ring_buf_avail(g_rb_eeg)    : 0;
        size_t mic_avail  = g_rb_mic    ? ring_buf_avail(g_rb_mic)    : 0;
        size_t dnl_avail  = g_rb_dnlink ? ring_buf_avail(g_rb_dnlink) : 0;
        ESP_LOGI(TAG, "ringbuf: eeg=%u mic=%u dnl=%u | acq=%s connected=%s",
                 (unsigned)eeg_avail, (unsigned)mic_avail, (unsigned)dnl_avail,
                 g_acq_running ? "on" : "off",
                 tcp_is_connected() ? "yes" : "no");
    }
}
