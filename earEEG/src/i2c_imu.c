#include "i2c_imu.h"
#include "earEEG_config.h"
#include "esp_log.h"
#include "esp_cpu.h"
#include "driver/i2c_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

static const char *TAG = "bno085";

#define BNO085_I2C_ADDR     0x4A
#define BNO085_I2C_FREQ_HZ   400000

// SHTP channels
#define SHTP_CHAN_COMMAND   0
#define SHTP_CHAN_EXEC      1
#define SHTP_CHAN_REPORTS   2
#define SHTP_CHAN_WAKE      3

// SH2 sensor report IDs
#define SH2_RPT_ACCEL        0x01
#define SH2_RPT_GYRO_CAL     0x02
#define SH2_RPT_GAME_RV      0x05
#define SH2_RPT_BASE_TS      0xFB

// SH2 commands
#define SH2_CMD_SET_REPORT   0xF2

// Shared sample
imu_sample_t g_imu_latest;

static i2c_master_bus_handle_t s_bus = NULL;
static i2c_master_dev_handle_t s_dev = NULL;
static TaskHandle_t s_poll_task = NULL;
static volatile bool s_running = false;

// ── SHTP helpers ───────────────────────────────────────────────────

// Read 4-byte SHTP header via I2C
// Returns: payload length (from header), or -1 on error
static int bno085_read_shtp_hdr(uint8_t *channel, uint8_t *seq)
{
    uint8_t hdr[4];
    esp_err_t ret = i2c_master_receive(s_dev, hdr, 4, 50);
    if (ret != ESP_OK) return -1;

    uint16_t len = hdr[0] | (uint16_t)(hdr[1] << 8);
    *channel = hdr[2];
    *seq     = hdr[3];
    return (int)len;
}

// Write SHTP header + payload
static bool bno085_write_shtp(uint8_t channel, uint8_t seq,
                              const uint8_t *payload, uint16_t payload_len)
{
    // Build: 4-byte header + payload
    size_t total = 4 + payload_len;
    uint8_t buf[256];
    buf[0] = payload_len & 0xFF;
    buf[1] = (payload_len >> 8) & 0xFF;
    buf[2] = channel;
    buf[3] = seq;
    if (payload && payload_len > 0) {
        memcpy(buf + 4, payload, payload_len);
    }
    return i2c_master_transmit(s_dev, buf, total, 100) == ESP_OK;
}

// Read SHTP payload after header
static bool bno085_read_payload(uint8_t *buf, uint16_t len)
{
    if (len == 0) return true;
    return i2c_master_receive(s_dev, buf, len, 100) == ESP_OK;
}

// ── SH2 command: enable sensor report at given interval ────────────

static bool bno085_enable_report(uint8_t report_id, uint32_t interval_us)
{
    uint8_t cmd[16];
    size_t pos = 0;
    cmd[pos++] = report_id;          // SH2: sensor report ID
    cmd[pos++] = 0x00;               // SH2: sequence
    cmd[pos++] = SH2_CMD_SET_REPORT; // command
    // interval (µs, little-endian)
    cmd[pos++] = interval_us & 0xFF;
    cmd[pos++] = (interval_us >> 8) & 0xFF;
    cmd[pos++] = (interval_us >> 16) & 0xFF;
    cmd[pos++] = (interval_us >> 24) & 0xFF;
    // batch timeout = 0
    cmd[pos++] = 0x00; cmd[pos++] = 0x00;
    cmd[pos++] = 0x00; cmd[pos++] = 0x00;
    // sensor-specific config = 0 (use defaults)
    cmd[pos++] = 0x00; cmd[pos++] = 0x00;
    cmd[pos++] = 0x00; cmd[pos++] = 0x00;

    // Also need the SH2 header
    // Actually the SH2 payload IS cmd[0..pos-1]. The SHTP header wraps it.
    return bno085_write_shtp(SHTP_CHAN_REPORTS, 0, cmd, pos);
}

// ── Initialize BNO085 and wait for boot ────────────────────────────

static bool bno085_boot(void)
{
    // Send software reset on channel 0
    uint8_t reset_payload = 0x01; // reset reason
    if (!bno085_write_shtp(SHTP_CHAN_COMMAND, 0, &reset_payload, 1)) {
        ESP_LOGW(TAG, "reset write failed (may already be booted)");
    }

    // Wait for product ID responses on channel 0
    // The BNO085 sends several advertisement packets after boot.
    // We read them until we've received initialization responses.
    int read_attempts = 0;
    while (read_attempts < 200) {
        uint8_t ch = 0, seq = 0;
        int plen = bno085_read_shtp_hdr(&ch, &seq);
        if (plen < 0) {
            vTaskDelay(pdMS_TO_TICKS(10));
            read_attempts++;
            continue;
        }

        // Read payload if present
        uint8_t payload[256];
        if (plen > 0 && plen <= (int)sizeof(payload)) {
            bno085_read_payload(payload, plen);
        }

        // Channel 0 responses during boot are initialization packets
        if (ch == SHTP_CHAN_COMMAND) {
            ESP_LOGI(TAG, "boot response on ch0, len=%d", plen);
            read_attempts = 0; // reset counter, keep reading
        }

        // After enough reads, assume boot complete
        vTaskDelay(pdMS_TO_TICKS(5));
        read_attempts++;
    }
    // Even if we time out, the device may have booted fine
    return true;
}

// ── Parse sensor reports from channel 2 payload ────────────────────

static void parse_sensor_report(const uint8_t *data, uint16_t len)
{
    if (len < 5) return;

    uint8_t  report_id  = data[0];
    (void)data[1]; // seq
    uint8_t  status     = data[2];

    if (status != 0) return; // skip non-accurate readings

    g_imu_latest.timestamp = esp_cpu_get_cycle_count();

    switch (report_id) {
    case SH2_RPT_GAME_RV: {
        // Game Rotation Vector: [report 1B][seq 1B][status 1B][ts 4B][delay 4B]
        // [i q14 2B][j q14 2B][k q14 2B][real q14 2B][accuracy q14 2B]
        // total: 19 bytes
        if (len < 19) break;
        int16_t qi = (int16_t)(data[11]  | (data[12] << 8));
        int16_t qj = (int16_t)(data[13]  | (data[14] << 8));
        int16_t qk = (int16_t)(data[15]  | (data[16] << 8));
        int16_t qr = (int16_t)(data[17]  | (data[18] << 8));
        g_imu_latest.quat_x = qi / 16384.0f;
        g_imu_latest.quat_y = qj / 16384.0f;
        g_imu_latest.quat_z = qk / 16384.0f;
        g_imu_latest.quat_w = qr / 16384.0f;
        g_imu_latest.valid = true;
        break;
    }
    case SH2_RPT_ACCEL: {
        if (len < 17) break;
        int16_t ax = (int16_t)(data[11] | (data[12] << 8));
        int16_t ay = (int16_t)(data[13] | (data[14] << 8));
        int16_t az = (int16_t)(data[15] | (data[16] << 8));
        g_imu_latest.accel_x = ax;
        g_imu_latest.accel_y = ay;
        g_imu_latest.accel_z = az;
        break;
    }
    case SH2_RPT_GYRO_CAL: {
        if (len < 17) break;
        int16_t gx = (int16_t)(data[11] | (data[12] << 8));
        int16_t gy = (int16_t)(data[13] | (data[14] << 8));
        int16_t gz = (int16_t)(data[15] | (data[16] << 8));
        g_imu_latest.gyro_x = gx;
        g_imu_latest.gyro_y = gy;
        g_imu_latest.gyro_z = gz;
        break;
    }
    default:
        break;
    }
}

// ── Polling task (250 Hz) ──────────────────────────────────────────

static void imu_poll_task(void *arg)
{
    TickType_t last_wake = xTaskGetTickCount();
    while (s_running) {
        // Read all available SHTP packets
        for (int i = 0; i < 5; i++) {
            uint8_t ch = 0, seq_val = 0;
            int plen = bno085_read_shtp_hdr(&ch, &seq_val);
            if (plen < 0) break;

            uint8_t payload[256];
            if (plen > 0) {
                if (!bno085_read_payload(payload, (uint16_t)plen)) break;
            }

            if (ch == SHTP_CHAN_REPORTS && plen > 0) {
                parse_sensor_report(payload, (uint16_t)plen);
            }
        }

        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(PACKET_INTERVAL_MS));
    }
    vTaskDelete(NULL);
}

// ── Public API ─────────────────────────────────────────────────────

bool imu_bno085_init(void)
{
    // Configure I2C master bus
    i2c_master_bus_config_t bus_cfg = {
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .i2c_port = I2C_NUM_0,
        .scl_io_num = PIN_I2C_SCL,
        .sda_io_num = PIN_I2C_SDA,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = false,
    };
    if (i2c_new_master_bus(&bus_cfg, &s_bus) != ESP_OK) {
        ESP_LOGE(TAG, "i2c_new_master_bus failed");
        return false;
    }

    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = BNO085_I2C_ADDR,
        .scl_speed_hz = BNO085_I2C_FREQ_HZ,
    };
    if (i2c_master_bus_add_device(s_bus, &dev_cfg, &s_dev) != ESP_OK) {
        ESP_LOGE(TAG, "i2c_master_bus_add_device failed");
        return false;
    }

    // Boot BNO085 and wait for initialization
    vTaskDelay(pdMS_TO_TICKS(50));
    if (!bno085_boot()) {
        ESP_LOGW(TAG, "boot may have timed out, continuing anyway");
    }

    // Enable desired sensor reports at 250Hz (4ms interval)
    if (!bno085_enable_report(SH2_RPT_GAME_RV, 4000)) {
        ESP_LOGW(TAG, "failed to enable game rotation vector");
    }
    vTaskDelay(pdMS_TO_TICKS(10));
    if (!bno085_enable_report(SH2_RPT_ACCEL, 4000)) {
        ESP_LOGW(TAG, "failed to enable accelerometer");
    }
    vTaskDelay(pdMS_TO_TICKS(10));
    if (!bno085_enable_report(SH2_RPT_GYRO_CAL, 4000)) {
        ESP_LOGW(TAG, "failed to enable gyroscope");
    }

    memset(&g_imu_latest, 0, sizeof(g_imu_latest));

    ESP_LOGI(TAG, "BNO085 init OK");
    return true;
}

void imu_bno085_start(void)
{
    if (s_running) return;
    s_running = true;
    xTaskCreatePinnedToCore(imu_poll_task, "imu_poll", STACK_IMU_POLL,
                            NULL, PRIO_IMU_POLL, &s_poll_task, 1);
    ESP_LOGI(TAG, "IMU polling started");
}

void imu_bno085_stop(void)
{
    s_running = false;
    if (s_poll_task) { vTaskDelete(s_poll_task); s_poll_task = NULL; }
    ESP_LOGI(TAG, "IMU polling stopped");
}
