#include "i2c_bus.h"
#include "earEEG_config.h"
#include "esp_log.h"

static const char *TAG = "i2c_bus";

static i2c_master_bus_handle_t s_bus = NULL;

bool i2c_bus_init(void)
{
    if (s_bus) return true;

    i2c_master_bus_config_t bus_cfg = {
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .i2c_port = I2C_NUM_0,
        .scl_io_num = PIN_I2C_SCL,
        .sda_io_num = PIN_I2C_SDA,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    esp_err_t ret = i2c_new_master_bus(&bus_cfg, &s_bus);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "i2c_new_master_bus failed: %s", esp_err_to_name(ret));
        return false;
    }

    ESP_LOGI(TAG, "shared I2C0 bus initialized (SDA=%d SCL=%d)",
             PIN_I2C_SDA, PIN_I2C_SCL);
    return true;
}

bool i2c_bus_probe(uint8_t address, int timeout_ms)
{
    if (!i2c_bus_init()) return false;

    esp_err_t ret = i2c_master_probe(s_bus, address, timeout_ms);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "I2C device 0x%02X probe failed: %s",
                 address, esp_err_to_name(ret));
        return false;
    }
    return true;
}

bool i2c_bus_add_device(uint8_t address, uint32_t speed_hz,
                        i2c_master_dev_handle_t *device)
{
    if (!device || !i2c_bus_init()) return false;

    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = address,
        .scl_speed_hz = speed_hz,
    };
    esp_err_t ret = i2c_master_bus_add_device(s_bus, &dev_cfg, device);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "failed to add I2C device 0x%02X: %s",
                 address, esp_err_to_name(ret));
        return false;
    }
    return true;
}
