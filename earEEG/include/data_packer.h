#pragma once

#include <stdint.h>
#include <stdbool.h>

extern volatile bool g_acq_running;

// Initialize data packer resources. Returns true on success.
bool data_packer_init(void);

// Start the packer task (builds & sends TYPE=0x01 frames at 250 Hz).
void data_packer_start(void);

// Stop the packer task.
void data_packer_stop(void);
