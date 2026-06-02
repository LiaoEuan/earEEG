#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "driver/i2c_master.h"

// Create the shared I2C0 master bus on first use.
bool i2c_bus_init(void);

// Attach a device to the shared I2C0 bus.
bool i2c_bus_add_device(uint8_t address, uint32_t speed_hz,
                        i2c_master_dev_handle_t *device);

// Check that a device acknowledges its address on the shared bus.
bool i2c_bus_probe(uint8_t address, int timeout_ms);
