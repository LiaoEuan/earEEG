#pragma once

#include <stdint.h>
#include <stdbool.h>

// Initialize NVS, netif, and Wi-Fi STA. Blocks until connected.
bool wifi_sta_init(void);

// Return true if Wi-Fi is connected.
bool wifi_sta_is_connected(void);

// Get current IP address as string (caller must free).
char *wifi_sta_get_ip(void);
