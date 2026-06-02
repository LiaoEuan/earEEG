#pragma once

#include <stdbool.h>

// Configure WM8960 for 44.1 kHz, 16-bit stereo headphone playback.
// The codec remains an I2S slave; ESP32 supplies BCLK, WS and DAC data.
// The Waveshare board supplies its own MCLK oscillator.
bool wm8960_init_playback(void);
