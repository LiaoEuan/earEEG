#pragma once

#include <stdint.h>
#include <stdbool.h>

// Initialize NVS, netif, and Wi-Fi soft-AP. Does not block (AP is immediately available).
bool wifi_ap_init(void);

// Return true if at least one station is connected to the AP.
bool wifi_ap_has_client(void);

// Get AP's IP address as string (caller must free). Always returns "192.168.4.1".
char *wifi_ap_get_ip(void);
