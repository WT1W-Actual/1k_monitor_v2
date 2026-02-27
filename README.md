# WT1W Ham Monitor - Virtual FT-1000MP

A virtual ham radio interface simulating the Yaesu FT-1000MP Mark-V transceiver. It includes a realistic front panel, CAT serial support, and a built-in HTTP API for remote control.

## Features

### Radio Interface
- Dual VFO (A/B) with independent frequency and mode
- VFO drag tuning (1.8-30 MHz)
- Numeric keypad frequency entry
- Mode selection: LSB, USB, CW, AM, FM
- Antenna switching (ANT 1 / ANT 2)
- Tuner toggle
- AF/SUB AF/RF/POWER sliders
- SHIFT/WIDTH/NOTCH interactive knobs
- APF/NR/CONTOUR filter matrix
- Memory channels (0-9)
- Split operation toggle

### Display and UX
- Dual amber frequency displays
- Mode LEDs and control indicators
- RX / PO / SWR segmented meters
- Connection status indicator
- Temporary status banner notifications
- Keyboard help overlay (`Ctrl+H`)
- Settings persistence in `~/.1k_monitor_settings.json`

### HTTP REST API
- Built-in API server (`127.0.0.1:8080` by default)
- JSON read/write endpoints for frequency, mode, VFO, split, controls, memory
- CORS enabled
- Full docs in `API_DOCUMENTATION.md`

## Installation

### Requirements
- Python 3.7+
- `customtkinter`
- `pyserial`

### Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python 1k_monitor_v2.py
```

## Configuration

Primary runtime settings are currently in `1k_monitor_v2.py`:
- `SERIAL_PORT`
- `BAUD_RATE`
- `MOCK_MODE`

Feature and UI constants are in `constants.py`:
- `ANIMATION_LOOP_MS`
- `HTTP_API_ENABLED`
- `HTTP_API_HOST`
- `HTTP_API_PORT`

## Keyboard Shortcuts

- `Up` / `Down`: +/-10 kHz
- `Shift+Up` / `Shift+Down`: +/-1 kHz
- `Ctrl+Left`: Toggle active VFO
- `Ctrl+M`: Cycle mode on active VFO
- `Ctrl+'`: Toggle split mode
- `Ctrl+H`: Toggle help overlay
- `Ctrl+S`: Save settings
- `Alt+0..9`: Recall memory channel
- `Alt+Shift+0..9`: Store memory channel

## API Quick Start

```bash
# Status
curl http://127.0.0.1:8080/api/status

# Set frequency on active VFO
curl -X POST http://127.0.0.1:8080/api/frequency \
  -H "Content-Type: application/json" \
  -d '{"frequency":"14.074.00"}'

# Set mode
curl -X POST http://127.0.0.1:8080/api/mode \
  -H "Content-Type: application/json" \
  -d '{"mode":"USB"}'

# Enable split
curl -X POST http://127.0.0.1:8080/api/split \
  -H "Content-Type: application/json" \
  -d '{"enable":true}'
```

See `API_DOCUMENTATION.md` for all endpoints and examples.

## Troubleshooting

- Ensure the app is running before calling API endpoints.
- If using real radio mode, verify cable, port, and baud settings.
- Check port usage with `lsof -i :8080` if API startup fails.
