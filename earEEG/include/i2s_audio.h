#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "ring_buf.h"

// Ring buffers defined in main.c, set before i2s_audio_start()
extern ring_buf_t *g_rb_mic;
extern ring_buf_t *g_rb_dnlink;

// Initialize I2S0 full-duplex audio for WM8960 playback and onboard mic capture.
// Returns true on success.
bool i2s_audio_init(void);

// Start audio streaming (call after ring buffers are ready).
void i2s_audio_start(void);

// Stop audio streaming.
void i2s_audio_stop(void);
