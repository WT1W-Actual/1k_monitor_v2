"""
Configuration constants for FT-1000MP Ham Monitor
Window size, update rates, UI dimensions, and tuning parameters
"""

# Window Configuration
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 480
WINDOW_TITLE = "WT1W Ham Monitor - Virtual FT-1000MP"

# Animation & Update Rates
ANIMATION_LOOP_MS = 100  # milliseconds (10 fps)
RADIO_LOOP_MS = 50       # Serial communication loop
METER_SMOOTHING = 0.2    # 0.0-1.0: Higher = more responsive
KNOB_SMOOTHING = 0.3     # For VFO and control knobs

# Frequency Tuning (via keyboard)
KEYBOARD_COARSE_STEP = 10    # kHz (arrow keys)
KEYBOARD_FINE_STEP = 1       # kHz (shift + arrow keys)
FREQUENCY_MIN = 1800         # 1.8 MHz
FREQUENCY_MAX = 30000        # 30 MHz

# VFO Knob Settings
VFO_A_CENTER_X = 480
VFO_A_CENTER_Y = 300
VFO_A_RADIUS = 90
VFO_B_CENTER_X = 900
VFO_B_CENTER_Y = 300
VFO_B_RADIUS = 65
DIMPLE_RADIUS_A = 65
DIMPLE_RADIUS_B = 50

# Control Slider Settings
SLIDER_WIDTH = 100
SLIDER_HEIGHT = 14

# Meter Settings
METER_SEGMENTS = 25
METER_GREEN_THRESHOLD = 0.68   # When to switch to yellow
METER_YELLOW_THRESHOLD = 0.84  # When to switch to red

# Serial Port Settings
BAUD_RATES_TO_TRY = [4800, 9600, 19200, 38400, 57600]
SERIAL_TIMEOUT = 0.3         # seconds
SERIAL_RETRY_INTERVAL = 5    # seconds between reconnect attempts
SERIAL_RETRY_MAX = 3         # initial attempts before giving up

# Memory Channel Settings
MEMORY_CHANNELS_COUNT = 10

# HTTP API Settings
HTTP_API_ENABLED = True      # Enable/disable HTTP API server
HTTP_API_PORT = 8080         # Port for HTTP API server
HTTP_API_HOST = "127.0.0.1"  # Bind to localhost only (secure). Use "0.0.0.0" for network access

# Text Sizes
FONT_SIZE_FREQ_MAIN = 50
FONT_SIZE_MODE = 12
FONT_SIZE_VFO_LABEL = 10
FONT_SIZE_BUTTON = 10
FONT_SIZE_HELP_TITLE = 14
FONT_SIZE_HELP_TEXT = 10

# License Information
APP_NAME = "WT1W Ham Monitor"
APP_VERSION = "2.0"
APP_CALLSIGN = "WT1W"
