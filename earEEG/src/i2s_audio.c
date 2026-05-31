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
    // 256 stereo samples = 1024 bytes of interleaved 16-bit L/R
    int16_t tx_buf[256 * 2];
    const size_t buf_bytes = sizeof(tx_buf);

    // Pre-fill first DMA buffer with silence
    memset(tx_buf, 0, buf_bytes);
    size_t written = 0;
    i2s_channel_write(s_tx_chan, tx_buf, buf_bytes, &written, portMAX_DELAY);

    while (s_running) {
        // Try to pull from downlink ring buffer
        if (g_rb_dnlink && ring_buf_avail(g_rb_dnlink) >= buf_bytes) {
            ring_buf_read(g_rb_dnlink, (uint8_t*)tx_buf, buf_bytes);
        } else {
            // No audio available → output silence
            memset(tx_buf, 0, buf_bytes);
        }

        size_t bytes_written = 0;
        esp_err_t ret = i2s_channel_write(s_tx_chan, tx_buf, buf_bytes,
                                          &bytes_written, pdMS_TO_TICKS(100));
        if (ret != ESP_OK && ret != ESP_ERR_TIMEOUT) {
            ESP_LOGW(TAG, "I2S TX write error: %d", ret);
        }
    }
    vTaskDelete(NULL);
}

// ── Public API ───────────────────────────────────────────────────────

bool i2s_audio_init(void)
{
    // ── RX channel (I2S1, INMP441, 16kHz mono) ──
    i2s_chan_config_t rx_chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
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

    // ── TX channel (I2S0, PCM5102, 44.1kHz stereo) ──
    i2s_chan_config_t tx_chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
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

    xTaskCreatePinnedToCore(i2s_rx_task_fn, "i2s_rx", 3072, NULL, 5,
                            &s_rx_task_handle, 1);
    xTaskCreatePinnedToCore(i2s_tx_task_fn, "i2s_tx", 3072, NULL, 5,
                            &s_tx_task_handle, 1);
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
