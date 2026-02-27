"""
Configuration module for the FT-1000MP Ham Monitor.

This module contains default settings and configuration options that can be 
customized by users.
"""

# Default serial port configuration
DEFAULT_SERIAL_PORT = '/dev/tty.usbserial-AB01'  # Mac example (can be auto-detected)
DEFAULT_BAUD_RATE = 4800

# Common baud rates for ham radios
BAUD_RATES_TO_TRY = [4800, 9600, 19200, 38400, 57600]

# Default mock mode setting
MOCK_MODE_DEFAULT = True

# UI Settings
UI_UPDATE_INTERVAL_MS = 50
ANIMATION_SPEED_FACTOR = 1.0

# Simulation settings
SIMULATION_SMOOTHING_FACTOR = 0.2