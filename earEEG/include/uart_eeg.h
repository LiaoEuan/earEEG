#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "ring_buf.h"

extern ring_buf_t *g_rb_eeg;

// EEG frame header byte from OpenBCI
#define OPENBCI_FRAME_START  0xA0
#define OPENBCI_FRAME_END_MIN 0xC0
#define OPENBCI_FRAME_END_MAX 0xCF

// Max raw bytes per OpenBCI frame (16ch + Daisy)
#define OPENBCI_FRAME_MAX    57

// Initialize OpenBCI UART and start parser task.
bool uart_eeg_init(void);

// Check whether the UART driver is ready for commands.
bool uart_eeg_is_ready(void);

// Start/stop EEG acquisition on the OpenBCI side (send 'b'/'s').
void uart_eeg_start_acq(void);
void uart_eeg_stop_acq(void);

// Forward raw bytes to OpenBCI UART (used by calibration CMD=0x10/0x11).
void uart_eeg_send_raw(const uint8_t *data, size_t len);
