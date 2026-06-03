#include "i2s_audio.h"
#include "earEEG_config.h"
#include "esp_log.h"
#include "esp_err.h"
#include "esp_cpu.h"
#include "driver/i2s_std.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

static const char *TAG = "i2s_audio";

// Global ring buffers — defined in main.c, set before i2s_audio_start()
extern ring_buf_t *g_rb_mic;
extern ring_buf_t *g_rb_dnlink;
extern volatile bool g_acq_running;

// I2S channel handles
static i2s_chan_handle_t s_tx_chan = NULL;
static i2s_chan_handle_t s_rx_chan = NULL;

static TaskHandle_t s_rx_task_handle = NULL;
static TaskHandle_t s_tx_task_handle = NULL;

static volatile bool s_running = false;

static bool write_tx_block(const int16_t *samples, size_t len,
                           unsigned *timeout_count)
{
    size_t total = 0;

    while (s_running && total < len) {
        size_t bytes_written = 0;
        esp_err_t ret = i2s_channel_write(s_tx_chan,
                                          (const uint8_t *)samples + total,
                                          len - total, &bytes_written,
                                          pdMS_TO_TICKS(100));
        total += bytes_written;

        if (ret == ESP_OK) {
            continue;
        }
        if (ret == ESP_ERR_TIMEOUT) {
            (*timeout_count)++;
            if (*timeout_count <= 5 || *timeout_count % 100 == 0) {
                ESP_LOGW(TAG, "I2S TX write timeout #%u (%u/%u bytes), retrying",
                         *timeout_count, (unsigned)total, (unsigned)len);
            }
            continue;
        }

        ESP_LOGW(TAG, "I2S TX write error: %d (%u/%u bytes)",
                 ret, (unsigned)total, (unsigned)len);
        return false;
    }
    return total == len;
}

// ── RX task: read I2S DMA → extract left mono → push to mic ring buffer ──

static void i2s_rx_task_fn(void *arg)
{
    // Buffer sized for one DMA read: I2S_DMA_BUF_LEN_RX stereo samples
    int16_t raw_buf[I2S_DMA_BUF_LEN_RX * 2];
    int16_t mono_buf[I2S_DMA_BUF_LEN_RX];

    while (s_running) {
        size_t bytes_read = 0;
        esp_err_t ret = i2s_channel_read(s_rx_chan, raw_buf, sizeof(raw_buf),
                                         &bytes_read, pdMS_TO_TICKS(100));
        if (ret != ESP_OK) {
            if (ret != ESP_ERR_TIMEOUT) {
                ESP_LOGW(TAG, "I2S RX read error: %d", ret);
            }
            continue;
        }

        uint64_t ts = esp_cpu_get_cycle_count();
        size_t stereo_samples = bytes_read / 4;  // 4 bytes = L(2) + R(2)
        if (stereo_samples == 0) continue;

        // Extract left-channel samples (INMP441 L/R pin tied to GND → data on left)
        for (size_t i = 0; i < stereo_samples; i++) {
            mono_buf[i] = raw_buf[i * 2];
        }
        size_t mono_bytes = stereo_samples * sizeof(int16_t);

        // Keep the RX channel running, but only retain samples while a
        // connected client has requested acquisition.
        if (!g_acq_running) continue;

        if (ring_buf_free(g_rb_mic) >= mono_bytes) {
            ring_buf_write(g_rb_mic, (uint8_t*)mono_buf, mono_bytes);
        } else {
            ESP_LOGW(TAG, "mic ring buffer full, dropping %u-byte block",
                     (unsigned)mono_bytes);
        }
        (void)ts; // cycle count captured but not embedded in ring buffer
    }
    vTaskDelete(NULL);
}

// ── TX task: read from downlink ring buffer → I2S DMA ──

static void i2s_tx_task_fn(void *arg)
{
    int16_t tx_buf[I2S_DMA_BUF_LEN_TX * TX_CHANNELS];
    const size_t buf_bytes = sizeof(tx_buf);
    const size_t start_watermark =
        (SAMPLE_RATE_TX * TX_CHANNELS * sizeof(int16_t) *
         DNLINK_START_WATERMARK_MS) / 1000;
    bool playing = false;
    bool had_underrun = false;
    unsigned underruns = 0;
    unsigned write_timeouts = 0;

    // Pre-fill first DMA buffer with silence
    memset(tx_buf, 0, buf_bytes);
    size_t written = 0;
    i2s_channel_write(s_tx_chan, tx_buf, buf_bytes, &written, portMAX_DELAY);

    while (s_running) {
        size_t avail = g_rb_dnlink ? ring_buf_avail(g_rb_dnlink) : 0;

        // First start: wait for the full start_watermark.
        // Recovery after underrun: only wait for one DMA block so the gap is
        // as short as possible (~6 ms instead of 300 ms).
        const size_t needed = (!playing && had_underrun) ? buf_bytes : start_watermark;

        if (!playing && avail >= needed) {
            playing = true;
            if (!had_underrun) {
                ESP_LOGI(TAG, "downlink playback started (%u bytes buffered)",
                         (unsigned)avail);
            } else {
                ESP_LOGI(TAG, "downlink underrun recovered (%u bytes buffered)",
                         (unsigned)avail);
            }
        }

        if (playing && avail >= buf_bytes) {
            ring_buf_read(g_rb_dnlink, (uint8_t*)tx_buf, buf_bytes);
#if AUDIO_TX_DIAG_MODE == 1
            for (size_t i = 0; i < I2S_DMA_BUF_LEN_TX; i++) {
                tx_buf[i * 2 + 1] = tx_buf[i * 2];
            }
#elif AUDIO_TX_DIAG_MODE == 2
            for (size_t i = 0; i < I2S_DMA_BUF_LEN_TX; i++) {
                tx_buf[i * 2 + 1] = 0;
            }
#endif
        } else {
            if (playing) {
                playing = false;
                had_underrun = true;
                underruns++;
                ESP_LOGW(TAG, "downlink underrun #%u, rebuffering", underruns);
            }
            memset(tx_buf, 0, buf_bytes);
        }

        if (!write_tx_block(tx_buf, buf_bytes, &write_timeouts)) {
            break;
        }
    }
    vTaskDelete(NULL);
}

// ── Public API ───────────────────────────────────────────────────────

bool i2s_audio_init(void)
{
    // ── RX channel (I2S1, INMP441, 16kHz mono) ──
    i2s_chan_config_t rx_chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
    rx_chan_cfg.dma_desc_num = I2S_DMA_BUF_COUNT_RX;
    rx_chan_cfg.dma_frame_num = I2S_DMA_BUF_LEN_RX;
    if (i2s_new_channel(&rx_chan_cfg, NULL, &s_rx_chan) != ESP_OK) {
        ESP_LOGE(TAG, "i2s_new_channel RX failed");
        return false;
    }

    i2s_std_config_t rx_std_cfg = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE_RX),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
                        AUDIO_BITS_PER_SAMPLE, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = PIN_I2S1_BCLK,
            .ws   = PIN_I2S1_LRCLK,
            .dout = I2S_GPIO_UNUSED,
            .din  = PIN_I2S1_DOUT,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv   = false,
            },
        },
    };
    if (i2s_channel_init_std_mode(s_rx_chan, &rx_std_cfg) != ESP_OK) {
        ESP_LOGE(TAG, "i2s_channel_init_std_mode RX failed");
        return false;
    }

    // TX channel (I2S0, WM8960, 44.1kHz stereo)
    i2s_chan_config_t tx_chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    tx_chan_cfg.dma_desc_num = I2S_DMA_BUF_COUNT_TX;
    tx_chan_cfg.dma_frame_num = I2S_DMA_BUF_LEN_TX;
    if (i2s_new_channel(&tx_chan_cfg, &s_tx_chan, NULL) != ESP_OK) {
        ESP_LOGE(TAG, "i2s_new_channel TX failed");
        return false;
    }

    i2s_std_config_t tx_std_cfg = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE_TX),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
                        AUDIO_BITS_PER_SAMPLE, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = PIN_I2S0_BCLK,
            .ws   = PIN_I2S0_LRCLK,
            .dout = PIN_I2S0_DIN,
            .din  = I2S_GPIO_UNUSED,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv   = false,
            },
        },
    };
    if (i2s_channel_init_std_mode(s_tx_chan, &tx_std_cfg) != ESP_OK) {
        ESP_LOGE(TAG, "i2s_channel_init_std_mode TX failed");
        return false;
    }

    ESP_LOGI(TAG, "I2S init OK (RX=%dHz TX=%dHz)", SAMPLE_RATE_RX, SAMPLE_RATE_TX);
#if AUDIO_TX_DIAG_MODE == 1
    ESP_LOGW(TAG, "diagnostic mode: duplicating left TX channel to right");
#elif AUDIO_TX_DIAG_MODE == 2
    ESP_LOGW(TAG, "diagnostic mode: forcing right TX channel to silence");
#endif
    return true;
}

void i2s_audio_start(void)
{
    if (s_running) return;
    if (!g_rb_mic || !g_rb_dnlink) {
        ESP_LOGE(TAG, "ring buffers not set, cannot start");
        return;
    }

    i2s_channel_enable(s_rx_chan);
    i2s_channel_enable(s_tx_chan);
    s_running = true;

    BaseType_t rx_ok = xTaskCreatePinnedToCore(i2s_rx_task_fn, "i2s_rx", 3072,
                                               NULL, PRIO_I2S_RX, &s_rx_task_handle, 1);
    BaseType_t tx_ok = xTaskCreatePinnedToCore(i2s_tx_task_fn, "i2s_tx", 3072,
                                               NULL, PRIO_I2S_TX, &s_tx_task_handle, 1);
    if (rx_ok != pdPASS || tx_ok != pdPASS) {
        ESP_LOGE(TAG, "failed to create I2S tasks");
        i2s_audio_stop();
        return;
    }
    ESP_LOGI(TAG, "I2S streaming started");
}

void i2s_audio_stop(void)
{
    s_running = false;
    if (s_rx_task_handle) { vTaskDelete(s_rx_task_handle); s_rx_task_handle = NULL; }
    if (s_tx_task_handle) { vTaskDelete(s_tx_task_handle); s_tx_task_handle = NULL; }
    i2s_channel_disable(s_rx_chan);
    i2s_channel_disable(s_tx_chan);
    ESP_LOGI(TAG, "I2S streaming stopped");
}
