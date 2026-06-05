# earEEG Upper Machine

This branch contains the cleaned PC-side software for the earEEG prototype.

Recommended runtime split:

1. Start `lsl_proxy` as the only TCP owner for the ESP32 connection.
2. Start the browser viewer to consume LSL streams and control the proxy.

Core modules:

- `upper_machine.common`: shared frame protocol parser and builders.
- `upper_machine.lsl_proxy`: TCP client, LSL outlets, local control API, and downlink audio streaming.
- `upper_machine.eeg_viewer`: browser UI, LSL visualization, impedance control, MIC monitoring, and NPZ session recording.
- `upper_machine.impedance`: pure impedance math and OpenBCI command helpers.

Debug-only direct TCP scripts and legacy CSV/WAV recorders are intentionally not included in this cleaned branch.
