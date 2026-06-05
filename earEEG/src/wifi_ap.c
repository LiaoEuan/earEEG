#include "earEEG_config.h"
#include "wifi_ap.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "esp_mac.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static const char *TAG = "wifi_ap";

static volatile int s_client_count = 0;
static esp_netif_t *s_netif = NULL;

// Default AP configuration (can be overridden via earEEG_config.h)
#ifndef AP_SSID
#define AP_SSID "earEEG"
#endif
#ifndef AP_PASSWORD
#define AP_PASSWORD "password123"
#endif
#ifndef AP_MAX_CONNECTIONS
#define AP_MAX_CONNECTIONS 4
#endif
#ifndef AP_CHANNEL
#define AP_CHANNEL 1
#endif

static void wifi_event_handler(void *arg, esp_event_base_t base,
                               int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_AP_START) {
        ESP_LOGI(TAG, "AP started. IP: 192.168.4.1");
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_AP_STACONNECTED) {
        wifi_event_ap_staconnected_t *event = (wifi_event_ap_staconnected_t *)data;
        ESP_LOGI(TAG, "station " MACSTR " connected", MAC2STR(event->mac));
        s_client_count++;
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_AP_STADISCONNECTED) {
        wifi_event_ap_stadisconnected_t *event = (wifi_event_ap_stadisconnected_t *)data;
        ESP_LOGI(TAG, "station " MACSTR " disconnected", MAC2STR(event->mac));
        s_client_count--;
    }
}

bool wifi_ap_init(void)
{
    // Init NVS
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    // Init TCP/IP stack
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    s_netif = esp_netif_create_default_wifi_ap();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    // Register event handler
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, NULL, NULL));

    // Configure Wi-Fi AP
    wifi_config_t wifi_cfg = {0};
    strncpy((char *)wifi_cfg.ap.ssid, AP_SSID, sizeof(wifi_cfg.ap.ssid) - 1);
    strncpy((char *)wifi_cfg.ap.password, AP_PASSWORD, sizeof(wifi_cfg.ap.password) - 1);
    wifi_cfg.ap.authmode = WIFI_AUTH_WPA2_PSK;
    wifi_cfg.ap.max_connection = AP_MAX_CONNECTIONS;
    wifi_cfg.ap.channel = AP_CHANNEL;
    wifi_cfg.ap.ssid_hidden = 0;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &wifi_cfg));

    ESP_LOGI(TAG, "Starting AP \"%s\" on channel %d...", AP_SSID, AP_CHANNEL);
    ESP_ERROR_CHECK(esp_wifi_start());

    return true;
}

bool wifi_ap_has_client(void)
{
    return s_client_count > 0;
}

char *wifi_ap_get_ip(void)
{
    char *buf = malloc(16);
    if (!buf) return NULL;
    snprintf(buf, 16, "192.168.4.1");
    return buf;
}
