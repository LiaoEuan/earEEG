# CLAUDE.md — earEEG Repository Guide

This file is the root guidance for agents working in:

`E:\yuan_space\10_projects\earEEG`

The repository contains three related but separate layers:

```text
earEEG/
  earEEG/                  # ESP32-S3 firmware, C / ESP-IDF / PlatformIO
  upper_machine/           # Existing PC bridge, Python, LSL, browser viewer
  ear_eeg_sound_lab/       # New sound-EEG application and R&D workspace
  recordings/              # Local NPZ session data, do not commit casually
```

## Current Project Direction

The current product direction is a sound-EEG closed-loop system:

```text
real or simulated earEEG device
  -> upper_machine.lsl_proxy
  -> LSL streams + local control API
  -> ear_eeg_sound_lab realtime engine
  -> visualization, music policy, session summary, LLM report
```

The next implementation stage is **not UI-first**. Build the first version of the application engine:

```text
NPZ / simulated stream
  -> EEG windowing
  -> preprocessing
  -> band-power features
  -> signal quality
  -> focus estimate
  -> structured output
```

For work inside `ear_eeg_sound_lab/`, also read:

- `ear_eeg_sound_lab/CLAUDE.md`
- `ear_eeg_sound_lab/docs/architecture.md`
- `ear_eeg_sound_lab/docs/data_contracts.md`
- `ear_eeg_sound_lab/docs/simulated_device.md`
- `ear_eeg_sound_lab/docs/roadmap.md`

For work inside `upper_machine/`, also read:

- `upper_machine/DEVELOPMENT_GUIDE.md`

## Layer Responsibilities

### `earEEG/` firmware

Owns hardware-facing logic:

- Wi-Fi AP / STA setup;
- TCP server;
- OpenBCI UART parsing;
- WM8960 audio I/O;
- IMU polling;
- binary protocol frame construction.

Change firmware only when the device protocol, sample timing, sensor behavior, or hardware pins need to change.

### `upper_machine/` bridge

Owns the stable PC-side bridge:

- `common/protocol.py`: protocol parser, CRC, sensor payload parsing;
- `common/eeg_units.py`: OpenBCI/ADS1299 counts and uV conversion;
- `lsl_proxy/`: the only normal TCP owner for the device;
- `eeg_viewer/`: current browser viewer and recording flow;
- `impedance/`: impedance math and command helpers.

Do not put product logic, recommendation logic, or focus-model logic into `lsl_proxy`.

### `ear_eeg_sound_lab/` application

Owns new product work:

- simulated device for hardware-free development;
- LSL / NPZ integrations;
- realtime EEG preprocessing;
- feature extraction;
- signal quality;
- focus estimate;
- music recommendation and adaptive switching;
- session summaries;
- report generation;
- future dashboard.

This layer should consume LSL streams and the proxy control API. It should not open a second normal TCP connection to the ESP32.

## Hard Rules

1. `lsl_proxy` is the only normal TCP owner.
   - Do not let viewer, app code, recorders, or experiments connect directly to ESP32 in normal operation.
   - Exception: the protocol-level simulated device accepts TCP from `lsl_proxy` for offline development.

2. Protocol changes must be full-chain changes.
   - Firmware, `upper_machine/common/protocol.py`, LSL outlet, viewer, recording, tests, and docs must stay aligned.

3. EEG raw payload is OpenBCI signed 24-bit big-endian.
   - Never parse EEG raw slots as little-endian.

4. Be explicit about EEG units.
   - Current streams and recordings may be raw counts, not uV.
   - Do not label values as uV unless conversion is actually applied.

5. Keep `common/protocol.py` small and dependency-light.
   - It must not depend on LSL, HTTP, UI, numpy, or product logic.

6. Do not make medical or clinical claims.
   - The first product uses algorithmic estimates such as focus score and signal quality.
   - Reports must separate measured facts, estimates, recommendations, and limitations.

7. Do not commit generated data by accident.
   - Avoid committing `.venv/`, `.pio/`, `__pycache__/`, large `recordings/`, local music, and generated reports.

## Development Commands

Run commands from the repository root:

```powershell
cd E:\yuan_space\10_projects\earEEG
```

Upper-machine help:

```powershell
uv run --project upper_machine python -m upper_machine.lsl_proxy.main --help
uv run --project upper_machine python -m upper_machine.eeg_viewer.main --help
```

Upper-machine tests:

```powershell
uv run --project upper_machine python -m unittest discover -s upper_machine -p "test_*.py"
```

Sound-lab tests:

```powershell
python -m unittest discover -s ear_eeg_sound_lab\tests -p "test_*.py"
```

Simulated device:

```powershell
python -m ear_eeg_sound_lab.src.simulated_device --auto-start --stats
```

Proxy against simulated device:

```powershell
uv run --project upper_machine python -m upper_machine.lsl_proxy.main --host 127.0.0.1 --port 8889 --lsl --start --stats
```

Proxy against real AP-mode device:

```powershell
uv run --project upper_machine python -m upper_machine.lsl_proxy.main --host 192.168.4.1 --port 8888 --lsl --start --stats
```

## Current Implementation Plan For Agents

When implementing the next stage, work in this order:

1. `ear_eeg_sound_lab/src/integrations/npz_loader.py`
   - Load existing `.npz` sessions.
   - Normalize EEG shape to `(channels, samples)`.
   - Do not change units.

2. `ear_eeg_sound_lab/src/realtime_engine/schemas.py`
   - Define dataclasses for windows, features, quality, focus, and engine output.

3. `ear_eeg_sound_lab/src/realtime_engine/windowing.py`
   - Slice EEG into fixed windows, initially 2 seconds with 0.5 second step.

4. `ear_eeg_sound_lab/src/realtime_engine/preprocessing.py`
   - First version: float conversion, NaN/Inf cleanup, per-channel demean.
   - Do not claim clinical-grade filtering.

5. `ear_eeg_sound_lab/src/realtime_engine/features.py`
   - FFT/Hann-based band power.
   - Bands: delta, theta, alpha, beta, gamma.
   - Output ratios such as theta/beta and alpha/beta.

6. `ear_eeg_sound_lab/src/realtime_engine/quality.py`
   - Detect flatline, high amplitude, bad channels, and poor windows.
   - Output score in `0.0..1.0`.

7. `ear_eeg_sound_lab/src/realtime_engine/focus.py`
   - Interpretable heuristic, not ML.
   - Output score in `0..100`, state label, quality, and reason codes.

8. `ear_eeg_sound_lab/src/realtime_engine/pipeline.py`
   - Chain all processing steps.

9. `ear_eeg_sound_lab/src/storage/session_summary.py`
   - Summarize many engine outputs for later reports.

Every module must have focused unit tests in `ear_eeg_sound_lab/tests/`.

## Code Quality Rules

- Prefer dataclasses for structured data.
- Use type hints for public functions.
- Public functions need docstrings describing:
  - input shape;
  - output shape;
  - unit assumptions;
  - whether the function changes units.
- Use numpy for first-version signal processing.
- Keep dependencies minimal.
- Avoid premature abstractions.
- Keep comments short and useful, especially around FFT, quality scoring, and focus heuristics.
- Clamp scores to their documented ranges.
- Sanitize NaN/Inf at module boundaries.

## Testing And Completion Rules

Before saying work is complete:

1. Run the relevant unit tests.
2. Report the exact command used.
3. Report whether it passed or failed.
4. If tests cannot be run, say why.

For protocol, sample-rate, channel-count, frame-type, command-ID, or unit changes, tests are mandatory.

## Protocol Change Checklist

When changing TCP frame format, payload layout, sample rates, channel counts, frame types, command IDs, or EEG units, update all relevant places:

1. `earEEG/include/protocol.h`
2. `earEEG/src/protocol.c`
3. `earEEG/include/earEEG_config.h`
4. `upper_machine/common/protocol.py`
5. `upper_machine/common/eeg_units.py` if unit conversion changes
6. test payload builders
7. `upper_machine/lsl_proxy/lsl_outlet.py`
8. `upper_machine/eeg_viewer/main.py`
9. `upper_machine/eeg_viewer/static/viewer.js`
10. `upper_machine/eeg_viewer/recording_service.py`
11. `upper_machine/impedance/core.py`
12. `ear_eeg_sound_lab/src/simulated_device/`
13. `ear_eeg_sound_lab/docs/data_contracts.md`
14. `upper_machine/DEVELOPMENT_GUIDE.md`
15. related tests

If possible, add a real-device or simulator golden frame test.

## Review Before Large Changes

Before large changes, inspect current git status and avoid overwriting unrelated user work:

```powershell
git status --short
```

If the task touches 3+ files or a shared contract, provide a short plan before editing.

## Documentation Expectations

When behavior changes, update docs near the behavior:

- root `CLAUDE.md` for repository-wide rules;
- `upper_machine/DEVELOPMENT_GUIDE.md` for bridge/protocol/viewer behavior;
- `ear_eeg_sound_lab/CLAUDE.md` for application-layer rules;
- `ear_eeg_sound_lab/docs/*.md` for product, architecture, data contracts, and roadmap.
