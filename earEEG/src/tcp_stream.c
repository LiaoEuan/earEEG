#include "tcp_stream.h"
#include "earEEG_config.h"
#include "protocol.h"
#include "crc16.h"
#include "ring_buf.h"
#include "i2c_imu.h"
#include "uart_eeg.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>
#include <string.h>
#include <errno.h>
#include <stddef.h>

static const char *TAG = "tcp";

// Extern ring buffers (owned by main.c, set before tcp_server_start)
extern ring_buf_t *g_rb_dnlink;
extern ring_buf_t *g_rb_eeg;
extern ring_buf_t *g_rb_mic;

// Extern acquisition state for command handler
extern volatile bool g_acq_running;

static volatile int  s_client_fd = -1;
static int           s_listen_fd = -1;
static TaskHandle_t  s_recv_task  = NULL;
static volatile bool s_running    = false;
static SemaphoreHandle_t s_send_mutex = NULL;

static void send_ack(uint8_t cmd_id, uint8_t status)
{
    ack_payload_t ack = { .cmd_id = cmd_id, .status = status };
    uint8_t frame[PROTO_FRAME_OVERHEAD + sizeof(ack)];
    size_t frame_len = 0;

    if (proto_build_frame(PROTO_TYPE_ACK, 0, (const uint8_t *)&ack, sizeof(ack),
                          frame, sizeof(frame), &frame_len)) {
        tcp_send(frame, frame_len);
    }
}

// ── Frame receive & dispatch ───────────────────────────────────────

static void dispatch_frame(proto_header_t *hdr, const uint8_t *payload)
{
    switch (hdr->type) {
    case PROTO_TYPE_DNLINK_AUDIO:
        // Skip CHN byte in payload — ring buffer expects pure PCM
        if (g_rb_dnlink && hdr->len > 1) {
            ring_buf_write(g_rb_dnlink, payload + 1, hdr->len - 1);
        }
        break;

    case PROTO_TYPE_COMMAND: {
        if (hdr->len < 1) break;
        const command_payload_t *cmd = (const command_payload_t *)payload;
        ESP_LOGI(TAG, "CMD 0x%02X", cmd->cmd_id);

        switch (cmd->cmd_id) {
        case CMD_START_ACQ:
            g_acq_running = true;
            send_ack(cmd->cmd_id, 0);
            break;
        case CMD_STOP_ACQ:
            g_acq_running = false;
            send_ack(cmd->cmd_id, 0);
            break;
        case CMD_IMPEDANCE_CTRL:
            {
                size_t asc_len = hdr->len - 1;
                if (asc_len > 0) {
                    uart_eeg_send_raw(payload + 1, asc_len);
                }
                ESP_LOGI(TAG, "impedance ctrl: %.*s", (int)asc_len, payload + 1);
                send_ack(cmd->cmd_id, 0);
            }
            break;
        case CMD_IMPEDANCE_STOP:
            {
                const char *stop_seq = "z100Zz200Zz300Zz400Zz500Zz600Zz700Zz800Z";
                uart_eeg_send_raw((const uint8_t *)stop_seq, strlen(stop_seq));
                ESP_LOGI(TAG, "impedance stop: sent disable-all");
                send_ack(cmd->cmd_id, 0);
            }
            break;
        default:
            ESP_LOGW(TAG, "unknown command 0x%02X", cmd->cmd_id);
            break;
        }
        break;
    }

    default:
        break;
    }
}

// ── Frame parser (state machine over TCP stream) ───────────────────

typedef enum {
    FS_SYNC0,
    FS_SYNC1,
    FS_HEADER,
    FS_PAYLOAD,
    FS_CRC,
} frame_state_t;

static void process_recv_bytes(const uint8_t *data, size_t len)
{
    static frame_state_t  s = FS_SYNC0;
    static proto_header_t s_hdr;
    static uint8_t        s_payload[2048];
    static size_t         s_payload_pos = 0;
    static size_t         s_header_pos = 0;
    static uint8_t        s_crc_buf[2];
    static size_t         s_crc_pos = 0;

    for (size_t i = 0; i < len; i++) {
        uint8_t b = data[i];

        switch (s) {
        case FS_SYNC0:
            if (b == PROTO_SYNC_0) s = FS_SYNC1;
            break;
        case FS_SYNC1:
            if (b == PROTO_SYNC_1) {
                s = FS_HEADER;
                s_hdr.sync0 = PROTO_SYNC_0;
                s_hdr.sync1 = PROTO_SYNC_1;
                s_header_pos = 2; // sync bytes already consumed
            } else {
                s = FS_SYNC0;
            }
            break;
        case FS_HEADER: {
            ((uint8_t *)&s_hdr)[s_header_pos++] = b;
            if (s_header_pos >= sizeof(s_hdr)) {
                s_hdr.len = ntohs(s_hdr.len);
                if (s_hdr.len > sizeof(s_payload)) {
                    ESP_LOGW(TAG, "payload too large: %u", s_hdr.len);
                    s = FS_SYNC0;
                } else if (s_hdr.len == 0) {
                    s = FS_CRC; // no payload, go straight to CRC
                    s_crc_pos = 0;
                } else {
                    s = FS_PAYLOAD;
                    s_payload_pos = 0;
                }
            }
            break;
        }
        case FS_PAYLOAD:
            s_payload[s_payload_pos++] = b;
            if (s_payload_pos >= s_hdr.len) {
                s = FS_CRC;
                s_crc_pos = 0;
            }
            break;
        case FS_CRC:
            s_crc_buf[s_crc_pos++] = b;
            if (s_crc_pos >= 2) {
                // Validate CRC
                uint16_t expected = s_crc_buf[1] << 8 | s_crc_buf[0];
                // Build full frame for CRC check (static — avoids stack overflow)
                size_t frame_size = PROTO_HEADER_SIZE + s_hdr.len;
                static uint8_t frame_buf[PROTO_HEADER_SIZE + 2048];
                size_t pos = 0;

                // Copy sync0, sync1, type (3 bytes)
                memcpy(frame_buf + pos, &s_hdr.sync0, offsetof(proto_header_t, len)); pos += offsetof(proto_header_t, len);
                // Copy len in network byte order (2 bytes)
                uint16_t len_be = htons(s_hdr.len);
                memcpy(frame_buf + pos, &len_be, sizeof(len_be)); pos += sizeof(len_be);
                // Copy timestamp (8 bytes, already LE in struct)
                memcpy(frame_buf + pos, &s_hdr.timestamp, sizeof(s_hdr.timestamp)); pos += sizeof(s_hdr.timestamp);
                if (s_hdr.len > 0) {
                    memcpy(frame_buf + pos, s_payload, s_hdr.len);
                }
                uint16_t calc = crc16_ibm(frame_buf, frame_size);
                if (calc == expected) {
                    dispatch_frame(&s_hdr, s_payload);
                } else {
                    ESP_LOGW(TAG, "CRC mismatch (calc=%04X expected=%04X)", calc, expected);
                }
                s = FS_SYNC0;
            }
            break;
        }
    }
}

// ── Receive task ───────────────────────────────────────────────────

static void tcp_recv_task(void *arg)
{
    uint8_t buf[4096];
    while (s_running) {
        if (s_client_fd < 0) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        ssize_t n = recv(s_client_fd, buf, sizeof(buf), 0);
        if (n > 0) {
            process_recv_bytes(buf, (size_t)n);
        } else if (n == 0) {
            ESP_LOGW(TAG, "client disconnected");
            close(s_client_fd);
            s_client_fd = -1;
        } else {
            // EAGAIN = no data yet; anything else = real error
            if (errno != EAGAIN && errno != EWOULDBLOCK) {
                ESP_LOGW(TAG, "recv error %d, closing", errno);
                close(s_client_fd);
                s_client_fd = -1;
            }
            vTaskDelay(1);  // 1 tick (~1ms), was 10ms — critical for throughput
        }
    }
    vTaskDelete(NULL);
}

// ── Public API ─────────────────────────────────────────────────────

int tcp_server_start(void)
{
    if (!s_send_mutex) {
        s_send_mutex = xSemaphoreCreateMutex();
        if (!s_send_mutex) {
            ESP_LOGE(TAG, "send mutex allocation failed");
            return -1;
        }
    }

    s_listen_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (s_listen_fd < 0) {
        ESP_LOGE(TAG, "socket() failed: %d", errno);
        return -1;
    }

    int opt = 1;
    setsockopt(s_listen_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port   = htons(TCP_SERVER_PORT),
        .sin_addr   = { .s_addr = INADDR_ANY },
    };

    if (bind(s_listen_fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        ESP_LOGE(TAG, "bind() failed: %d", errno);
        close(s_listen_fd);
        return -1;
    }

    if (listen(s_listen_fd, 1) < 0) {
        ESP_LOGE(TAG, "listen() failed: %d", errno);
        close(s_listen_fd);
        return -1;
    }

    ESP_LOGI(TAG, "listening on port %d", TCP_SERVER_PORT);

    // Accept one client (blocking)
    struct sockaddr_in client_addr;
    socklen_t addr_len = sizeof(client_addr);
    s_client_fd = accept(s_listen_fd, (struct sockaddr *)&client_addr, &addr_len);
    if (s_client_fd < 0) {
        ESP_LOGE(TAG, "accept() failed: %d", errno);
        close(s_listen_fd);
        return -1;
    }
    ESP_LOGI(TAG, "client connected from %s:%d",
             inet_ntoa(client_addr.sin_addr), ntohs(client_addr.sin_port));

    // Note: setsockopt(TCP_NODELAY / SO_RCVBUF) omitted — crashes on this lwIP build.
    // Throughput is managed by PC-side pacing instead.

    // Non-blocking recv with minimal polling delay (see tcp_recv_task)
    int flags = fcntl(s_client_fd, F_GETFL, 0);
    fcntl(s_client_fd, F_SETFL, flags | O_NONBLOCK);

    s_running = true;
    xTaskCreatePinnedToCore(tcp_recv_task, "tcp_recv", STACK_TCP_RECV,
                            NULL, PRIO_TCP_RECV, &s_recv_task, 0);

    return s_client_fd;
}

void tcp_server_stop(void)
{
    s_running = false;
    if (s_recv_task) { vTaskDelete(s_recv_task); s_recv_task = NULL; }
    if (s_client_fd >= 0) { close(s_client_fd); s_client_fd = -1; }
    if (s_listen_fd >= 0)  { close(s_listen_fd);  s_listen_fd = -1;  }
}

int tcp_send(const uint8_t *data, size_t len)
{
    if (!data || len == 0 || s_client_fd < 0 || !s_send_mutex) return -1;
    if (xSemaphoreTake(s_send_mutex, pdMS_TO_TICKS(1000)) != pdTRUE) return -1;

    size_t total = 0;
    while (total < len && s_client_fd >= 0) {
        ssize_t sent = send(s_client_fd, data + total, len - total, 0);
        if (sent > 0) {
            total += (size_t)sent;
            continue;
        }
        if (sent < 0 && errno == EINTR) continue;
        if (sent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            vTaskDelay(1);
            continue;
        }
        if (sent < 0 && (errno == ECONNRESET || errno == EPIPE)) {
            close(s_client_fd);
            s_client_fd = -1;
        }
        break;
    }

    xSemaphoreGive(s_send_mutex);
    return total == len ? (int)total : -1;
}

bool tcp_is_connected(void)
{
    return s_client_fd >= 0;
}
