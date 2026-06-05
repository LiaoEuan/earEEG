#pragma once

#include <stdint.h>
#include <stddef.h>

// CRC-16-IBM (0x8005, also known as CRC-16-MODBUS)
uint16_t crc16_ibm(const uint8_t *data, size_t len);
