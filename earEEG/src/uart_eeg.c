#include "uart_eeg.h"
#include "earEEG_config.h"
#include "esp_log.h"
#include "driver/uart.h"
#include "esp_rom_gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include <string.h>

static const char *TAG = "uart_eeg";

extern ring_buf_t *g_rb_eeg;

static QueueHandle_t s_uart_queue = NULL;
static TaskHandle_t  s_parser_task = NULL;
static volatile bool s_running = false;

static void eeg_parser_task(void *arg)
{
    uint8_t raw[OPENBCI_FRAME_MAX];
    uint8_t frame_buf[256];

    while (s_running) {
        uart_event_t event;
        if (xQueueReceive(s_uart_queue, &event, pdMS_TO_TICKS(50)) != pdTRUE) {
            continue;
        }

        if (event.type != UART_DATA || event.size == 0) {
            continue;
        }

        int bytes = uart_read_bytes(OPENBCI_UART_NUM, raw,
                                    (event.size < sizeof(raw)) ? event.size : sizeof(raw),
                                    pdMS_TO_TICKS(10));
        if (bytes <= 0) continue;

        for (int i = 0; i < bytes; i++) {
            if (raw[i] != OPENBCI_FRAME_START) continue;

            size_t remaining = (size_t)(bytes - i);
            if (remaining < 33) break;

            uint8_t footer = raw[i + 32];
            size_t frame_size;
            if (footer >= OPENBCI_FRAME_END_MIN && footer <= OPENBCI_FRAME_END_MAX) {
                frame_size = 33;
            } else if (remaining >= 57) {
                footer = raw[i + 56];
                if (footer >= OPENBCI_FRAME_END_MIN && footer <= OPENBCI_FRAME_END_MAX) {
                    frame_size = 57;
                } else {
                    continue;
                }
            } else {
                break;
            }

            // Valid frame. Entry format: [u16 channels][u16 eeg_bytes][raw eeg data]
            uint16_t num_ch = (frame_size == 57) ? 16 : 8;
            uint16_t eeg_bytes = num_ch * 3;
            size_t entry_size = sizeof(num_ch) + sizeof(eeg_bytes) + eeg_bytes;

            if (entry_size > sizeof(frame_buf)) {
                ESP_LOGW(TAG, "frame buffer overflow");
                continue;
            }

            size_t pos = 0;
            memcpy(frame_buf + pos, &num_ch, sizeof(num_ch)); pos += sizeof(num_ch);
            memcpy(frame_buf + pos, &eeg_bytes, sizeof(eeg_bytes)); pos += sizeof(eeg_bytes);
            memcpy(frame_buf + pos, raw + i + 2, eeg_bytes); pos += eeg_bytes;

            if (g_rb_eeg && ring_buf_free(g_rb_eeg) >= entry_size) {
                ring_buf_write(g_rb_eeg, frame_buf, entry_size);
            } else {
                ESP_LOGW(TAG, "eeg ring buffer full or null, dropping frame");
            }

            i += (frame_size - 1);
        }
    }
    vTaskDelete(NULL);
}

bool uart_eeg_init(void)
{
    const uart_config_t uart_cfg = {
        .baud_rate = OPENBCI_BAUDRATE,
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    esp_err_t ret = uart_driver_install(OPENBCI_UART_NUM, 2048, 256, 20,
                                        &s_uart_queue, 0);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "uart_driver_install failed: %d", ret);
        return false;
    }

    ret = uart_param_config(OPENBCI_UART_NUM, &uart_cfg);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "uart_param_config failed: %d", ret);
        return false;
    }

    // Route UART1 TX/RX to GPIO43/44 via GPIO matrix.
    // Avoid uart_set_pin() — it calls gpio_set_direction which hangs
    // when console UART0 already uses these pins.
    // ESP32-S3 GPIO matrix signal IDs: U1TXD=8, U1RXD=9
    esp_rom_gpio_connect_out_signal(PIN_UART_TX, 8, false, false);
    esp_rom_gpio_connect_in_signal(PIN_UART_RX, 9, false);

    uart_set_rx_timeout(OPENBCI_UART_NUM, 3);

    ESP_LOGI(TAG, "UART EEG init OK (baud=%d)", OPENBCI_BAUDRATE);
    return true;
}

void uart_eeg_start_acq(void)
{
    const char *cmd = "b";
    uart_write_bytes(OPENBCI_UART_NUM, cmd, strlen(cmd));

    // Start parser task *after* sending start command.
    // Don't start in init — OpenBCI streams on power-up,
    // and Core 0 can't handle LWIP + UART interrupts simultaneously.
    if (!s_running) {
        s_running = true;
    xTaskCreatePinnedToCore(eeg_parser_task, "eeg_parser", STACK_EEG_PARSER,
                            NULL, PRIO_EEG_PARSER, &s_parser_task, 1);
    }
    ESP_LOGI(TAG, "sent start command");
}

void uart_eeg_stop_acq(void)
{
    const char *cmd = "s";
    uart_write_bytes(OPENBCI_UART_NUM, cmd, strlen(cmd));
    ESP_LOGI(TAG, "sent stop command");
}

void uart_eeg_send_raw(const uint8_t *data, size_t len)
{
    if (!data || len == 0) return;
    uart_write_bytes(OPENBCI_UART_NUM, data, len);
}
