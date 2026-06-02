#include "wm8960.h"
#include "i2c_bus.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "wm8960";

#define WM8960_I2C_ADDR       0x1A
#define WM8960_I2C_FREQ_HZ    100000

#define WM8960_REG_LOUT1_VOL  0x02
#define WM8960_REG_ROUT1_VOL  0x03
#define WM8960_REG_CLOCKING1  0x04
#define WM8960_REG_DAC_CTRL1  0x05
#define WM8960_REG_AUDIO_IF   0x07
#define WM8960_REG_LDAC_VOL   0x0A
#define WM8960_REG_RDAC_VOL   0x0B
#define WM8960_REG_RESET      0x0F
#define WM8960_REG_PWR_MGMT1  0x19
#define WM8960_REG_PWR_MGMT2  0x1A
#define WM8960_REG_LOUT_MIX   0x22
#define WM8960_REG_ROUT_MIX   0x25
#define WM8960_REG_PWR_MGMT3  0x2F

static i2c_master_dev_handle_t s_dev = NULL;

static bool wm8960_write_reg(uint8_t reg, uint16_t value)
{
    uint8_t data[2] = {
        (uint8_t)((reg << 1) | ((value >> 8) & 0x01)),
        (uint8_t)(value & 0xFF),
    };
    esp_err_t ret = i2c_master_transmit(s_dev, data, sizeof(data), 100);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "register 0x%02X write failed: %s",
                 reg, esp_err_to_name(ret));
        return false;
    }
    return true;
}

bool wm8960_init_playback(void)
{
    if (!i2c_bus_add_device(WM8960_I2C_ADDR, WM8960_I2C_FREQ_HZ, &s_dev)) {
        ESP_LOGE(TAG, "failed to attach codec to I2C bus");
        return false;
    }

    // Reset, establish VMID, then enable only the DAC, headphone drivers and
    // output mixers required by the first playback-only migration stage.
    if (!wm8960_write_reg(WM8960_REG_RESET,     0x000)) return false;
    if (!wm8960_write_reg(WM8960_REG_PWR_MGMT1, 0x1C0)) return false;
    vTaskDelay(pdMS_TO_TICKS(50));
    if (!wm8960_write_reg(WM8960_REG_PWR_MGMT2, 0x1E0)) return false;
    if (!wm8960_write_reg(WM8960_REG_PWR_MGMT3, 0x018)) return false;

    // ESP32 is I2S master. MCLK is 256 * 44.1 kHz; the codec uses MCLK
    // directly, with 16-bit Philips I2S frames and no PLL.
    if (!wm8960_write_reg(WM8960_REG_CLOCKING1, 0x000)) return false;
    if (!wm8960_write_reg(WM8960_REG_AUDIO_IF,  0x002)) return false;

    // Route both DAC channels to the headphone mixers and start at a
    // conservative -20 dB analogue headphone level.
    if (!wm8960_write_reg(WM8960_REG_LDAC_VOL,  0x0FF)) return false;
    if (!wm8960_write_reg(WM8960_REG_RDAC_VOL,  0x1FF)) return false;
    if (!wm8960_write_reg(WM8960_REG_LOUT_MIX,  0x100)) return false;
    if (!wm8960_write_reg(WM8960_REG_ROUT_MIX,  0x100)) return false;
    if (!wm8960_write_reg(WM8960_REG_LOUT1_VOL, 0x065)) return false;
    if (!wm8960_write_reg(WM8960_REG_ROUT1_VOL, 0x165)) return false;
    if (!wm8960_write_reg(WM8960_REG_DAC_CTRL1, 0x000)) return false;

    ESP_LOGI(TAG, "playback initialized (44.1kHz, 16-bit stereo, HP=-20dB)");
    return true;
}

