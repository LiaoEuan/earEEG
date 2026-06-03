#include "wm8960.h"
#include "i2c_bus.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "wm8960";

#define WM8960_I2C_ADDR       0x1A
#define WM8960_I2C_FREQ_HZ    100000
#define WM8960_I2C_RETRIES    5

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
#define WM8960_REG_ADD_CTRL1  0x17
#define WM8960_REG_ADD_CTRL2  0x18
#define WM8960_REG_LOUT_MIX   0x22
#define WM8960_REG_ROUT_MIX   0x25
#define WM8960_REG_LOUT2_VOL  0x28
#define WM8960_REG_ROUT2_VOL  0x29
#define WM8960_REG_PWR_MGMT3  0x2F
#define WM8960_REG_ADD_CTRL4  0x30
#define WM8960_REG_CLASS_D1   0x31

static i2c_master_dev_handle_t s_dev = NULL;

static bool wm8960_wait_for_ack(const char *stage)
{
    for (int attempt = 1; attempt <= WM8960_I2C_RETRIES; attempt++) {
        if (i2c_bus_probe(WM8960_I2C_ADDR, 100)) return true;

        ESP_LOGW(TAG, "codec %s probe attempt %d/%d failed",
                 stage, attempt, WM8960_I2C_RETRIES);
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    ESP_LOGE(TAG, "codec did not acknowledge after %s", stage);
    return false;
}

static bool wm8960_write_reg(uint8_t reg, uint16_t value)
{
    uint8_t data[2] = {
        (uint8_t)((reg << 1) | ((value >> 8) & 0x01)),
        (uint8_t)(value & 0xFF),
    };
    esp_err_t ret = ESP_FAIL;
    for (int attempt = 1; attempt <= WM8960_I2C_RETRIES; attempt++) {
        ret = i2c_master_transmit(s_dev, data, sizeof(data), 100);
        if (ret == ESP_OK) return true;

        ESP_LOGW(TAG, "register 0x%02X write attempt %d/%d failed: %s",
                 reg, attempt, WM8960_I2C_RETRIES, esp_err_to_name(ret));
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    ESP_LOGE(TAG, "register 0x%02X write failed after retries", reg);
    return false;
}

bool wm8960_init_playback(void)
{
    vTaskDelay(pdMS_TO_TICKS(100));
    if (!wm8960_wait_for_ack("startup")) return false;

    if (!i2c_bus_add_device(WM8960_I2C_ADDR, WM8960_I2C_FREQ_HZ, &s_dev)) {
        ESP_LOGE(TAG, "failed to attach codec to I2C bus");
        return false;
    }

    // Reset, establish VMID, then enable only the DAC, headphone drivers and
    // output mixers required by the first playback-only migration stage.
    if (!wm8960_write_reg(WM8960_REG_RESET,     0x000)) return false;
    vTaskDelay(pdMS_TO_TICKS(100));
    if (!wm8960_wait_for_ack("reset")) return false;
    if (!wm8960_write_reg(WM8960_REG_PWR_MGMT1, 0x1C0)) return false;
    vTaskDelay(pdMS_TO_TICKS(50));

    // Match Waveshare's playback example: the module oscillator is used
    // directly, with no ESP32 MCLK output and no codec PLL.
    if (!wm8960_write_reg(WM8960_REG_PWR_MGMT2,  0x1E0)) return false;
    if (!wm8960_write_reg(WM8960_REG_PWR_MGMT3,  0x00C)) return false;
    if (!wm8960_write_reg(WM8960_REG_CLOCKING1,  0x000)) return false;
    if (!wm8960_write_reg(WM8960_REG_DAC_CTRL1,  0x000)) return false;
    if (!wm8960_write_reg(WM8960_REG_AUDIO_IF,  0x002)) return false;

    // Stage one only validates the headphone jack. Keep the speaker/Class-D
    // path and input side tone path off; they add avoidable hiss on headphones.
    if (!wm8960_write_reg(WM8960_REG_LDAC_VOL,  0x0FF)) return false;
    if (!wm8960_write_reg(WM8960_REG_RDAC_VOL,  0x1F8)) return false;
    if (!wm8960_write_reg(WM8960_REG_LOUT1_VOL, 0x160)) return false;
    if (!wm8960_write_reg(WM8960_REG_ROUT1_VOL, 0x160)) return false;
    if (!wm8960_write_reg(WM8960_REG_LOUT2_VOL, 0x000)) return false;
    if (!wm8960_write_reg(WM8960_REG_ROUT2_VOL, 0x000)) return false;
    if (!wm8960_write_reg(WM8960_REG_CLASS_D1,  0x000)) return false;
    if (!wm8960_write_reg(WM8960_REG_LOUT_MIX,  0x100)) return false;
    if (!wm8960_write_reg(WM8960_REG_ROUT_MIX,  0x100)) return false;

    ESP_LOGI(TAG, "playback initialized (headphone-only, onboard MCLK, "
             "44.1kHz, 16-bit stereo, DAC-only output mixers)");
    return true;
}
