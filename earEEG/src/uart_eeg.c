#include "uart_eeg.h"
#include "earEEG_config.h"
#include "esp_log.h"
#include "driver/uart.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include <string.h>

static const char *TAG = "uart_eeg";

extern ring_buf_t *g_rb_eeg;

static QueueHandle_t s_uart_queue = NULL;
static TaskHandle_t  s_parser_task = NULL;
static volatile bool s_running = false;
static volatile bool s_ready = false;

static bool is_frame_footer(uint8_t value)
{
    return value >= OPENBCI_FRAME_END_MIN && value <= OPENBCI_FRAME_END_MAX;
}

static void store_eeg_frame(const uint8_t *raw, size_t frame_size)
{
    uint8_t frame_buf[256];
    uint16_t num_ch = (frame_size == 57) ? 16 : 8;
    uint16_t eeg_bytes = num_ch * 3;
    size_t entry_size = sizeof(num_ch) + sizeof(eeg_bytes) + eeg_bytes;

    size_t pos = 0;
    memcpy(frame_buf + pos, &num_ch, sizeof(num_ch)); pos += sizeof(num_ch);
    memcpy(frame_buf + pos, &eeg_bytes, sizeof(eeg_bytes)); pos += sizeof(eeg_bytes);
    memcpy(frame_buf + pos, raw + 2, eeg_bytes);

    if (g_rb_eeg && ring_buf_free(g_rb_eeg) >= entry_size) {
        ring_buf_write(g_rb_eeg, frame_buf, entry_size);
    } else {
        ESP_LOGW(TAG, "eeg ring buffer full or null, dropping frame");
    }
}

static void parse_eeg_bytes(const uint8_t *data, size_t len)
{
    static uint8_t stream_buf[OPENBCI_FRAME_MAX * 2];
    static size_t stream_len = 0;

    for (size_t i = 0; i < len; i++) {
        if (stream_len == sizeof(stream_buf)) {
            memmove(stream_buf, stream_buf + 1, --stream_len);
        }
        stream_buf[stream_len++] = data[i];

        while (stream_len > 0) {
            if (stream_buf[0] != OPENBCI_FRAME_START) {
                memmove(stream_buf, stream_buf + 1, --stream_len);
                continue;
            }
            if (stream_len < 33) break;

            size_t frame_size = 0;
            if (is_frame_footer(stream_buf[32])) {
                frame_size = 33;
            } else if (stream_len < 57) {
                break;
            } else if (is_frame_footer(stream_buf[56])) {
                frame_size = 57;
            } else {
                memmove(stream_buf, stream_buf + 1, --stream_len);
                continue;
            }

            store_eeg_frame(stream_buf, frame_size);
            stream_len -= frame_size;
            memmove(stream_buf, stream_buf + frame_size, stream_len);
        }
    }
}

static void eeg_parser_task(void *arg)
{
    uint8_t raw[OPENBCI_FRAME_MAX];

    while (s_running) {
        uart_event_t event;
        if (xQueueReceive(s_uart_queue, &event, pdMS_TO_TICKS(50)) != pdTRUE) {
            continue;
        }

        if (event.type == UART_FIFO_OVF || event.type == UART_BUFFER_FULL) {
            ESP_LOGW(TAG, "UART RX overflow, flushing input");
            uart_flush_input(OPENBCI_UART_NUM);
            xQueueReset(s_uart_queue);
            continue;
        }
        if (event.type != UART_DATA || event.size == 0) {
            continue;
        }

        size_t remaining = event.size;
        while (remaining > 0) {
            size_t request = remaining < sizeof(raw) ? remaining : sizeof(raw);
            int bytes = uart_read_bytes(OPENBCI_UART_NUM, raw, request,
                                        pdMS_TO_TICKS(10));
            if (bytes <= 0) break;
            parse_eeg_bytes(raw, (size_t)bytes);
            remaining -= (size_t)bytes;
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

    // GPIO43/44 are available after moving the console to USB Serial/JTAG.
    ret = uart_set_pin(OPENBCI_UART_NUM, PIN_UART_TX, PIN_UART_RX,
                       UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "uart_set_pin failed: %d", ret);
        return false;
    }

    uart_set_rx_timeout(OPENBCI_UART_NUM, 3);

    s_ready = true;
    ESP_LOGI(TAG, "UART EEG init OK (baud=%d)", OPENBCI_BAUDRATE);
    return true;
}

bool uart_eeg_is_ready(void)
{
    return s_ready;
}

void uart_eeg_start_acq(void)
{
    if (!s_ready) return;
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
    if (!s_ready) return;
    const char *cmd = "s";
    uart_write_bytes(OPENBCI_UART_NUM, cmd, strlen(cmd));
    ESP_LOGI(TAG, "sent stop command");
}

void uart_eeg_send_raw(const uint8_t *data, size_t len)
{
    if (!s_ready || !data || len == 0) return;
    uart_write_bytes(OPENBCI_UART_NUM, data, len);
}
