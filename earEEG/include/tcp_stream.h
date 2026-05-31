#pragma once

#include <stdint.h>
#include <stdbool.h>

// Start TCP server and accept a client. Blocks until connected.
// Spawns receive tasks. Returns connected socket fd, or -1 on error.
int tcp_server_start(void);

// Stop server and close socket.
void tcp_server_stop(void);

// Send a raw buffer over TCP. Returns bytes sent, or -1 on error.
int tcp_send(const uint8_t *data, size_t len);

// Check if client is connected.
bool tcp_is_connected(void);
