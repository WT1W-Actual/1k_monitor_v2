import customtkinter as ctk
import serial
import serial.tools.list_ports
import threading
import time
import math
import random
import json
import os
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from colors import *
from constants import *

# --- CONFIGURATION ---
SERIAL_PORT = 'COM3'  # Windows example
# SERIAL_PORT = '/dev/tty.usbserial-AB01'  # Mac example (can be auto-detected)
BAUD_RATE = 4800  # Will be auto-detected if radio is found
MOCK_MODE = False  # Set to False to use real radio

# CAT framing (FT-1000MP commonly uses 8N2)
SERIAL_BYTESIZE = serial.EIGHTBITS
SERIAL_PARITY = serial.PARITY_NONE
SERIAL_STOPBITS = serial.STOPBITS_TWO
SERIAL_PROFILES = [
    (serial.EIGHTBITS, serial.PARITY_NONE, serial.STOPBITS_TWO, "8N2"),
    (serial.EIGHTBITS, serial.PARITY_NONE, serial.STOPBITS_ONE, "8N1"),
]
CAT_FREQ_LSB_FIRST = True  # Command parameters are sent LSB-first (manual coding examples)
CAT_DEBUG = False
CAT_COMMAND_DELAY_S = 0.08   # Conservative default wait after CAT TX before reading
CAT_FREQ_READ_DELAY_S = 0.08 # Frequency/status reads need a little more settling time
CAT_METER_READ_DELAY_S = 0.05 # F7 meter replies are short and can be polled faster
CAT_POLL_INTERVAL_S = 0.05   # Keep the poll loop moving so meters feel live
CAT_POLL_METER = True
CAT_READ_OPCODE = 0x03       # Try 0x03 first (read frequency per manual); fall back to 0x00 if no RX
CAT_USE_STATUS_UPDATE_FOR_FREQ = False  # 0x10 format is radio/firmware specific; disabled until mapped reliably
CAT_STATUS_UPDATE_PARAM = 0x03  # 0x03 = Main VFO-A & Sub VFO-B Data (32 bytes)
CAT_SYNC_MODE_FROM_STATUS = True
CAT_SYNC_ANTENNA_FROM_STATUS = True

# Common baud rates for ham radios
BAUD_RATES_TO_TRY = [4800, 9600, 19200, 38400, 57600]


def resolve_serial_settings():
    """Return serial settings, preferring explicit config over auto-detection."""
    configured_port = SERIAL_PORT.strip() if isinstance(SERIAL_PORT, str) else SERIAL_PORT
    configured_baud = BAUD_RATE

    if configured_port and configured_baud:
        return configured_port, int(configured_baud), False

    detected_port, detected_baud = autodetect_serial_port()
    return detected_port, detected_baud, True


def build_serial_connection(
    port_name,
    baud_rate,
    timeout_seconds,
    bytesize=SERIAL_BYTESIZE,
    parity=SERIAL_PARITY,
    stopbits=SERIAL_STOPBITS,
):
    """Create a serial connection using explicit CAT framing settings."""
    return serial.Serial(
        port_name,
        baud_rate,
        timeout=timeout_seconds,
        write_timeout=timeout_seconds,
        bytesize=bytesize,
        parity=parity,
        stopbits=stopbits,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )


def _hex_bytes(data):
    return " ".join(f"{b:02X}" for b in data)


def cat_debug_log(direction, payload):
    if CAT_DEBUG:
        print(f"CAT {direction}: {_hex_bytes(payload)}")


def frequency_display_to_10hz(freq_display):
    """Convert XX.XXX.XX-style display frequency into 10 Hz units."""
    digits = "".join(ch for ch in str(freq_display) if ch.isdigit())
    if not digits:
        return None
    return int(digits)


def frequency_10hz_to_display(freq_10hz):
    """Convert 10 Hz units to XX.XXX.XX-style display frequency."""
    freq_str = f"{int(freq_10hz):07d}"
    if len(freq_str) == 6:
        return f"{freq_str[0]}.{freq_str[1:4]}.{freq_str[4:6]}"
    return f"{freq_str[0:2]}.{freq_str[2:5]}.{freq_str[5:7]}"


def decode_frequency_candidates_from_cat_bytes(freq_bytes):
    """Decode FT-1000MP CAT frequency bytes, returning plausible values in 10 Hz units.

    Tries both byte orders and both BCD resolution conventions:
      - 10 Hz resolution MSB-first  (FT-1000MP standard, e.g. 01 43 20 00 = 14.320 MHz)
      - 1 Hz  resolution MSB-first  (some Yaesu variants,  e.g. 14 32 00 00 = 14.320 MHz)
    """
    if len(freq_bytes) != 4:
        return []

    def is_valid_bcd(byte_value):
        return ((byte_value >> 4) & 0x0F) <= 9 and (byte_value & 0x0F) <= 9

    if not all(is_valid_bcd(b) for b in freq_bytes):
        return []

    # Build candidate digit-strings for forward (MSB-first) and reversed (LSB-first).
    fwd = "".join(f"{b:02x}" for b in freq_bytes)
    rev = "".join(f"{b:02x}" for b in reversed(freq_bytes))

    decoded = []
    for candidate in (fwd, rev):
        if len(candidate) != 8 or not candidate.isdigit():
            continue
        val = int(candidate)

        # Interpret as 10 Hz units (1,432,000 × 10 Hz = 14.32 MHz)
        if 1.8 <= val / 100000.0 <= 30.0:
            decoded.append(val)

        # Interpret as 1 Hz units (14,320,000 Hz = 14.32 MHz), convert to 10 Hz units
        if 1.8 <= val / 1000000.0 <= 30.0:
            decoded.append(val // 10)

    # Preserve insertion order while removing duplicates.
    return list(dict.fromkeys(decoded))


def decode_status_record_frequency_10hz(record_bytes):
    """Decode 16-byte Status Update record frequency (bytes 1-4) to 10 Hz units.

    FT-1000MP status records encode frequency as a 32-bit binary value where
    one count equals 0.625 Hz.
    """
    if len(record_bytes) < 5:
        return None

    raw = int.from_bytes(record_bytes[1:5], byteorder="big", signed=False)
    freq_hz = raw * 0.625
    if not (1_800_000 <= freq_hz <= 30_000_000):
        return None
    return int(round(freq_hz / 10.0))


def decode_status_vfo_pair_10hz(status_data):
    """Decode VFO-A/VFO-B frequencies from Status Update U=03 (32-byte payload)."""
    if len(status_data) < 32:
        return None, None

    vfo_a = decode_status_record_frequency_10hz(status_data[0:16])
    vfo_b = decode_status_record_frequency_10hz(status_data[16:32])
    return vfo_a, vfo_b


def choose_stable_vfo_assignment(decoded_1, decoded_2, current_a_display, current_b_display):
    """Assign decoded frequencies to VFO-A/VFO-B with minimum jump from current UI state.

    Some rigs/firmware report current/other order instead of fixed A/B order.
    This chooser keeps labels stable by selecting the mapping closest to existing A/B values.
    """
    if decoded_1 is None:
        return None, None

    if decoded_2 is None:
        return decoded_1, None

    cur_a = frequency_display_to_10hz(current_a_display)
    cur_b = frequency_display_to_10hz(current_b_display)
    if cur_a is None or cur_b is None:
        return decoded_1, decoded_2

    direct_cost = abs(decoded_1 - cur_a) + abs(decoded_2 - cur_b)
    swapped_cost = abs(decoded_2 - cur_a) + abs(decoded_1 - cur_b)
    if swapped_cost < direct_cost:
        return decoded_2, decoded_1
    return decoded_1, decoded_2


def decode_status_mode(byte_value):
    """Decode operating mode from status record mode bits.

    Manual examples represent mode in the low-order trio (e.g. ...010 => CW),
    with other bits used for flags/dummy values.
    """
    mode_code = byte_value & 0x07
    mode_map = {
        0b000: "LSB",
        0b001: "USB",
        0b010: "CW",
        0b011: "AM",
        0b100: "FM",
    }
    return mode_map.get(mode_code)


def decode_status_antenna(byte_value):
    """Decode antenna selection from VFO/MEM flags byte.

    ANT SELECT bits are flags representing A/B/RX antenna state.
    """
    ant_code = (byte_value >> 2) & 0x03
    if ant_code == 0b00:
        return 1
    if ant_code == 0b01:
        return 2
    return None


def decode_status_transmitting(byte_value):
    """Decode RX/TX state from the status flags byte.

    Hamlib's FT-1000MP status definitions map bit 5 (0x20) as RX/TX.
    """
    return bool(byte_value & 0x20)


def select_frequency_from_stream(stream_bytes, current_freq_display):
    """Scan a raw CAT byte stream and pick the most plausible frequency."""
    if len(stream_bytes) < 4:
        return None

    candidates = []
    for i in range(0, len(stream_bytes) - 3):
        window = stream_bytes[i:i + 4]
        for freq_10hz in decode_frequency_candidates_from_cat_bytes(window):
            candidates.append(freq_10hz)

    if not candidates:
        return None

    # Keep order while removing duplicates.
    candidates = list(dict.fromkeys(candidates))
    current_10hz = frequency_display_to_10hz(current_freq_display)
    if current_10hz is None:
        selected_10hz = candidates[0]
    else:
        selected_10hz = min(candidates, key=lambda f: abs(f - current_10hz))

    return frequency_10hz_to_display(selected_10hz)


def has_valid_frequency_in_payload(payload, opcode, status_param, current_freq_display):
    """Validate whether a payload contains a usable frequency for a given query type."""
    if not payload:
        return False

    if opcode == 0x10 and status_param == 0x03:
        vfo_a_10hz, _ = decode_status_vfo_pair_10hz(payload)
        return vfo_a_10hz is not None

    return select_frequency_from_stream(payload, current_freq_display) is not None


def encode_frequency_to_cat_bytes(freq_display, lsb_first=True):
    """Encode XX.XXX.XX display frequency into 4 packed-BCD CAT bytes."""
    digits = "".join(ch for ch in str(freq_display) if ch.isdigit())
    if not digits:
        raise ValueError("Frequency contains no digits")
    digits = digits.rjust(7, "0")
    digits = digits[:7].rjust(8, "0")

    bcd = [int(digits[i:i + 2], 16) for i in range(0, 8, 2)]
    if lsb_first:
        bcd.reverse()
    return bcd

def probe_radio(port_name, baud_rate):
    """Probe a serial port at a specific baud rate to see if an FT-1000MP is connected"""
    try:
        ser = build_serial_connection(port_name, baud_rate, timeout_seconds=0.3)
        time.sleep(0.1)  # Give port time to settle
        
        # Send frequency read command (opcode 0x03)
        cmd_freq = bytearray([0x00, 0x00, 0x00, 0x00, 0x03])
        ser.write(cmd_freq)
        
        # Wait for response (should be 5 bytes)
        data = ser.read(5)
        ser.close()
        
        if len(data) == 5:
            return True
        else:
            return False
            
    except Exception as e:
        # Log the exception but don't crash
        print(f"Error probing radio on {port_name} at {baud_rate}: {e}")
        return False

def autodetect_serial_port():
    """Auto-detect the FT-1000MP serial port and baud rate by probing"""
    try:
        ports = serial.tools.list_ports.comports()
        
        # Look for USB serial adapters
        usb_ports = []
        for port in ports:
            # Common USB serial adapter patterns
            if any(keyword in port.description.lower() for keyword in ['usb', 'serial', 'uart', 'cp210', 'ft232', 'ch340']):
                usb_ports.append(port.device)
                print(f"Found USB serial port: {port.device} - {port.description}")
        
        if not usb_ports:
            print("No USB serial ports found. Using default from config.")
            return SERIAL_PORT, BAUD_RATE
        
        # Probe each port at each baud rate to find the radio
        print(f"\nProbing {len(usb_ports)} port(s) for FT-1000MP...")
        for port in usb_ports:
            print(f"Testing {port}...")
            for baud in BAUD_RATES_TO_TRY:
                if probe_radio(port, baud):
                    print(f"✓ FT-1000MP found on {port} at {baud} baud\n")
                    return port, baud
            print(f"  No response at any baud rate")
        
        # No radio found, use first port with default baud
        print(f"No radio detected. Using first available port: {usb_ports[0]} at {BAUD_RATE} baud\n")
        return usb_ports[0] if usb_ports else SERIAL_PORT, BAUD_RATE
        
    except Exception as e:
        print(f"Error during serial port autodetection: {e}")
        # Return default values on error
        return SERIAL_PORT, BAUD_RATE

# --- HTTP API SERVER ---
class RadioAPIHandler(BaseHTTPRequestHandler):
    """HTTP API request handler for remote radio control"""
    
    radio_app = None  # Will be set to the HamSimulatorApp instance
    
    def log_message(self, format, *args):
        """Override to suppress default logging (optional)"""
        pass  # Comment this out to enable request logging
    
    def _set_headers(self, status=200, content_type='application/json'):
        """Set HTTP response headers with CORS support"""
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')  # CORS
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def _send_json(self, data, status=200):
        """Send JSON response"""
        self._set_headers(status)
        self.wfile.write(json.dumps(data).encode())
    
    def _send_error_json(self, message, status=400):
        """Send error response"""
        self._send_json({'error': message, 'success': False}, status)

    def _parse_bool(self, value):
        """Parse booleans from JSON values and common string forms."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        raise ValueError("Boolean value expected")

    def _normalize_frequency(self, value):
        """Normalize frequency to XX.XXX.XX-style string and validate ham range."""
        if isinstance(value, (int, float)):
            freq_mhz = float(value)
        elif isinstance(value, str):
            digits = "".join(ch for ch in value if ch.isdigit())
            if not digits:
                raise ValueError("Invalid frequency format")
            if len(digits) <= 2:
                freq_mhz = float(digits)
            elif len(digits) <= 5:
                freq_mhz = float(f"{digits[:2]}.{digits[2:]}")
            else:
                # Treat as 10 Hz resolution, e.g. 1407400 -> 14.07400 MHz
                freq_mhz = int(digits) / 100000.0
        else:
            raise ValueError("Invalid frequency type")

        if not (1.8 <= freq_mhz <= 30.0):
            raise ValueError("Frequency must be between 1.8 and 30.0 MHz")

        freq_10hz = int(round(freq_mhz * 100000))
        freq_str = f"{freq_10hz:07d}"
        if len(freq_str) == 6:
            return f"{freq_str[0]}.{freq_str[1:4]}.{freq_str[4:6]}"
        return f"{freq_str[0:2]}.{freq_str[2:5]}.{freq_str[5:7]}"
    
    def do_OPTIONS(self):
        """Handle CORS preflight requests"""
        self._set_headers()
    
    def do_GET(self):
        """Handle GET requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if not self.radio_app:
            return self._send_error_json("Radio app not initialized", 500)
        
        # GET /api/status - Full radio status
        if path == '/api/status':
            status = {
                'success': True,
                'frequency_a': self.radio_app.frequency,
                'frequency_b': self.radio_app.frequency_vfo_b,
                'mode_a': self.radio_app.mode,
                'mode_b': self.radio_app.mode_vfo_b,
                'active_vfo': self.radio_app.active_vfo,
                'transmitting': self.radio_app.transmitting,
                'split_enabled': self.radio_app.split_enabled,
                'af_gain': self.radio_app.af_gain,
                'sub_af_gain': self.radio_app.sub_af_gain,
                'rf_gain': self.radio_app.rf_gain,
                'power_level': self.radio_app.power_level,
                'shift': self.radio_app.shift,
                'width': self.radio_app.width,
                'notch': self.radio_app.notch,
                'antenna': self.radio_app.antenna,
                'tuner_active': self.radio_app.tuner_active,
                'meter_level': self.radio_app.meter_level,
                'mock_mode': MOCK_MODE,
                'selected_memory': self.radio_app.selected_memory,
            }
            return self._send_json(status)
        
        # GET /api/frequency - Current frequency (active VFO)
        elif path == '/api/frequency':
            freq = self.radio_app.frequency if self.radio_app.active_vfo == "A" else self.radio_app.frequency_vfo_b
            return self._send_json({'success': True, 'frequency': freq})
        
        # GET /api/mode - Current mode (active VFO)
        elif path == '/api/mode':
            mode = self.radio_app.mode if self.radio_app.active_vfo == "A" else self.radio_app.mode_vfo_b
            return self._send_json({'success': True, 'mode': mode})
        
        # GET /api/vfo - Active VFO
        elif path == '/api/vfo':
            return self._send_json({'success': True, 'active_vfo': self.radio_app.active_vfo})
        
        # GET /api/split - Split mode status
        elif path == '/api/split':
            return self._send_json({'success': True, 'split_enabled': self.radio_app.split_enabled})
        
        # GET /api/memory/:id - Get memory channel
        elif path.startswith('/api/memory/'):
            try:
                ch = int(path.split('/')[-1])
                if 0 <= ch < 10:
                    mem = self.radio_app.memory_channels[ch]
                    return self._send_json({'success': True, 'channel': ch, 'memory': mem})
                else:
                    return self._send_error_json("Channel must be 0-9")
            except ValueError:
                return self._send_error_json("Invalid channel number")
        
        # GET /api/controls - All control values
        elif path == '/api/controls':
            controls = {
                'success': True,
                'af_gain': self.radio_app.af_gain,
                'sub_af_gain': self.radio_app.sub_af_gain,
                'rf_gain': self.radio_app.rf_gain,
                'power_level': self.radio_app.power_level,
                'shift': self.radio_app.shift,
                'width': self.radio_app.width,
                'notch': self.radio_app.notch,
            }
            return self._send_json(controls)
        
        else:
            return self._send_error_json("Endpoint not found", 404)
    
    def do_POST(self):
        """Handle POST requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if not self.radio_app:
            return self._send_error_json("Radio app not initialized", 500)
        
        # Parse JSON body
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode() if content_length > 0 else '{}'
        
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return self._send_error_json("Invalid JSON")
        
        # POST /api/frequency - Set frequency
        if path == '/api/frequency':
            freq = data.get('frequency')
            vfo = data.get('vfo', self.radio_app.active_vfo)
            if freq is None:
                return self._send_error_json("Missing 'frequency' parameter")
            if vfo not in ["A", "B"]:
                return self._send_error_json("VFO must be 'A' or 'B'")

            try:
                normalized_freq = self._normalize_frequency(freq)
            except ValueError as e:
                return self._send_error_json(str(e))

            if vfo == "A":
                self.radio_app.frequency = normalized_freq
                self.radio_app.set_mode_for_frequency("A")
                self.radio_app.send_frequency_to_radio("A")
                self.radio_app.send_mode_to_radio(self.radio_app.mode, "A")
            else:
                self.radio_app.frequency_vfo_b = normalized_freq
                self.radio_app.set_mode_for_frequency("B")
                self.radio_app.send_frequency_to_radio("B")
                self.radio_app.send_mode_to_radio(self.radio_app.mode_vfo_b, "B")
            return self._send_json({'success': True, 'frequency': normalized_freq, 'vfo': vfo})
        
        # POST /api/mode - Set mode
        elif path == '/api/mode':
            mode = data.get('mode')
            vfo = data.get('vfo', self.radio_app.active_vfo)
            valid_modes = ["LSB", "USB", "CW", "AM", "FM"]
            if mode and mode in valid_modes:
                if vfo == "A":
                    self.radio_app.mode = mode
                    self.radio_app.send_mode_to_radio(mode, "A")
                else:
                    self.radio_app.mode_vfo_b = mode
                    self.radio_app.send_mode_to_radio(mode, "B")
                return self._send_json({'success': True, 'mode': mode, 'vfo': vfo})
            else:
                return self._send_error_json(f"Invalid mode. Must be one of: {valid_modes}")
        
        # POST /api/vfo - Switch VFO
        elif path == '/api/vfo':
            vfo = data.get('vfo')
            if vfo in ["A", "B"]:
                self.radio_app.active_vfo = vfo
                return self._send_json({'success': True, 'active_vfo': vfo})
            else:
                return self._send_error_json("VFO must be 'A' or 'B'")
        
        # POST /api/split - Toggle split mode
        elif path == '/api/split':
            enable = data.get('enable')
            if enable is not None:
                try:
                    self.radio_app.split_enabled = self._parse_bool(enable)
                except ValueError:
                    return self._send_error_json("'enable' must be a boolean")
            else:
                self.radio_app.split_enabled = not self.radio_app.split_enabled
            return self._send_json({'success': True, 'split_enabled': self.radio_app.split_enabled})
        
        # POST /api/transmit - Toggle transmit
        elif path == '/api/transmit':
            enable = data.get('enable')
            if enable is not None:
                try:
                    self.radio_app.transmitting = self._parse_bool(enable)
                except ValueError:
                    return self._send_error_json("'enable' must be a boolean")
            else:
                self.radio_app.transmitting = not self.radio_app.transmitting
            return self._send_json({'success': True, 'transmitting': self.radio_app.transmitting})
        
        # POST /api/controls - Set control values
        elif path == '/api/controls':
            updated = {}
            controls = [
                'af_gain', 'sub_af_gain', 'rf_gain', 'power_level', 'shift', 'width', 'notch'
            ]
            try:
                for control in controls:
                    if control in data:
                        value = max(0, min(100, int(data[control])))
                        setattr(self.radio_app, control, value)
                        updated[control] = value
            except (TypeError, ValueError):
                return self._send_error_json("Control values must be integers between 0 and 100")
            
            return self._send_json({'success': True, 'updated': updated})
        
        # POST /api/memory/:id - Store to memory
        elif path.startswith('/api/memory/') and '/store' in path:
            try:
                ch = int(path.split('/')[-2])
                if 0 <= ch < 10:
                    self.radio_app.store_memory(ch)
                    return self._send_json({'success': True, 'message': f'Stored to memory {ch}'})
                else:
                    return self._send_error_json("Channel must be 0-9")
            except (ValueError, IndexError):
                return self._send_error_json("Invalid channel number")
        
        else:
            return self._send_error_json("Endpoint not found", 404)
    
    def do_PUT(self):
        """Handle PUT requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if not self.radio_app:
            return self._send_error_json("Radio app not initialized", 500)
        
        # PUT /api/memory/:id - Recall from memory
        if path.startswith('/api/memory/'):
            try:
                ch = int(path.split('/')[-1])
                if 0 <= ch < 10:
                    self.radio_app.recall_memory(ch)
                    return self._send_json({'success': True, 'message': f'Recalled memory {ch}'})
                else:
                    return self._send_error_json("Channel must be 0-9")
            except ValueError:
                return self._send_error_json("Invalid channel number")
        
        else:
            return self._send_error_json("Endpoint not found", 404)

class HamSimulatorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window Setup
        self.title(WINDOW_TITLE)
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        ctk.set_appearance_mode("Dark")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Settings file for persistence
        self.settings_file = Path.home() / ".1k_monitor_settings.json"
        
        # Cache for display strings (optimization)
        self.cached_freq_a = None
        self.cached_freq_b = None
        self.cached_mode_a = None
        self.cached_mode_b = None
        self.cached_antenna = None
        self.cached_meter_level = -1
        self.cached_transmitting = False
        self.show_help = False
        
        # Serial connection tracking
        self.last_reconnect_attempt = 0
        self.connection_stable = False
        self.cat_read_opcode_working = None  # Will be set to 0x03, 0x00, or 0x10 after successful probe
        self.cat_read_status_param_working = None
        self.cat_read_enabled = False
        self.mode_sync_block_until = 0.0
        
        # Status message system
        self.status_message = None
        self.status_message_until = 0

        # Data Variables
        self.frequency = "14.320.00"
        self.frequency_vfo_b = "18.120.00"
        self.mode = "USB"
        self.mode_vfo_b = "LSB"
        self.meter_level = 0
        self.transmitting = False
        self.active_vfo = "A"
        self.running = True
        self.af_gain = 50  # 0-100
        self.sub_af_gain = 50  # 0-100 (VFO B volume)
        self.rf_gain = 80  # 0-100
        self.power_level = 100  # 0-100 (transmit power)
        self.power_meter_level = 0  # 0-255 (output power meter)
        self.swr_level = 0  # 0-255 (SWR meter)
        self.radio_tx_active = False  # Actual TX state inferred from CAT status
        self.tx_meter_hold_until = 0.0  # Hold PO/SWR briefly across missed reads
        self.last_tx_meter_update = 0.0
        self.shift = 50  # 0-100 (IF shift)
        self.width = 50  # 0-100 (filter width)
        self.notch = 50  # 0-100 (notch filter)
        # Filter Matrix states
        self.apf_filters = {250: False, 500: False, 1000: False, 1500: False, 2000: False}
        self.nr_filters = {500: False, 1000: False, 1500: False, 2000: False, 3000: False}
        self.contour_mode = 0  # 0=OFF, 1=Low-Cut, 2=Mid-Cut, 3=High-Cut
        self.nr_off = True  # NR OFF state
        self.filters_off = True  # Legacy - for backward compatibility
        self.antenna = 1   # 1 or 2
        self.tuner_active = False
        self.freq_entry_buffer = ""  # For direct frequency entry
        self.freq_entry_mode = False
        self.vfo_a_last_angle = None  # Track last drag angle for VFO A
        self.vfo_b_last_angle = None  # Track last drag angle for VFO B
        self.serial_port = None  # Serial port for radio communication
        self.serial_lock = threading.Lock()  # Protect serial port from concurrent access
        self.serial_profile_name = "unknown"
        self.last_polled_freq = None
        self.last_polled_freq_hits = 0
        
        # Memory Channels (10 channels for storing freq + mode pairs)
        self.memory_channels = [
            {'freq_a': f'{70.000 + i*0.5:.3f}', 'mode_a': 'USB', 'freq_b': f'{18.000 + i*0.5:.3f}', 'mode_b': 'LSB'}
            for i in range(10)
        ]
        self.selected_memory = 0  # Currently selected memory channel (0-9)
        
        # Split Frequency Mode
        self.split_enabled = False  # When True, TX on VFO A, RX on VFO B
        
        # Dynamic Elements (Store IDs for updating)
        self.ui_elements = {}

        # Canvas Setup (The Radio Face)
        self.canvas = ctk.CTkCanvas(self, width=WINDOW_WIDTH, height=WINDOW_HEIGHT, bg=COLOR_CHASSIS, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Drawing Layers
        self.draw_chassis()
        self.draw_display_window()
        self.draw_knobs()
        self.draw_buttons()
        self.draw_filter_matrix()
        self.draw_connection_status()
        
        self.init_dynamic_display()

        # Load saved settings
        self.load_settings()
        
        # Bind keyboard controls
        self.bind("<Up>", lambda e: self.keyboard_frequency_adjust(10))  # +10 kHz
        self.bind("<Down>", lambda e: self.keyboard_frequency_adjust(-10))  # -10 kHz
        self.bind("<Shift-Up>", lambda e: self.keyboard_frequency_adjust(1))  # +1 kHz
        self.bind("<Shift-Down>", lambda e: self.keyboard_frequency_adjust(-1))  # -1 kHz
        self.bind("<Control-Left>", lambda e: self.switch_vfo())  # Toggle VFO
        self.bind("<Control-m>", lambda e: self.cycle_mode())  # Cycle mode
        self.bind("<Control-h>", lambda e: self.toggle_help())  # Toggle help
        self.bind("<Control-s>", lambda e: self.save_settings())  # Save settings
        
        # Memory Channel Bindings (Alt+0 through Alt+9)
        for i in range(10):
            self.bind(f"<Alt-Key-{i}>", lambda e, ch=i: self.recall_memory(ch))  # Recall
            self.bind(f"<Alt-Shift-Key-{i}>", lambda e, ch=i: self.store_memory(ch))  # Store
        
        # Split Mode Toggle (Ctrl+')
        self.bind("<Control-apostrophe>", lambda e: self.toggle_split())

        # Start Radio Thread
        self.thread = threading.Thread(target=self.radio_loop, daemon=True)
        self.thread.start()

        # Start HTTP API Server (if enabled)
        self.api_server = None
        if HTTP_API_ENABLED:
            self.start_api_server()

        # Start Animation Loop (100ms = 10 fps - more efficient)
        self.animate()

    def draw_chassis(self):
        """Draws the static background elements"""
        # Main Faceplate bevels
        self.canvas.create_line(0, 130, 1200, 130, fill="#111111", width=2) # Separation between display and controls
        
        # Yaesu Logo
        self.canvas.create_text(160, 145, text="YAESU", fill="#cccccc", font=("Times New Roman", 16, "bold"))
        self.canvas.create_text(1050, 145, text="FT-1000MP  MARK-V", fill="#cccccc", font=("Arial", 12, "italic bold"))

    def draw_display_window(self):
        """Draws the main black display area"""
        # The glass window
        self.canvas.create_rectangle(50, 20, 1150, 120, fill=COLOR_DISPLAY_BG, outline="#444444", width=3)
        
        # Static labels inside display
        self.canvas.create_text(80, 35, text="METER", fill="#555555", font=("Arial", 8), anchor="w")
        self.canvas.create_text(80, 105, text="S / PO", fill="#555555", font=("Arial", 8), anchor="w")

    def draw_knobs(self):
        """Draws the VFO knobs"""
        # === Main VFO A ===
        cx, cy = 480, 300
        r = 90
        # Outer Grip
        self.canvas.create_oval(cx-r, cy-r, cx+r, cy+r, fill=COLOR_KNOB_MAIN, outline="#000000", width=2)
        # Inner Ring
        r_inner = 75
        self.canvas.create_oval(cx-r_inner, cy-r_inner, cx+r_inner, cy+r_inner, outline=COLOR_KNOB_RING, width=15)
        # Center Cap
        r_cap = 30
        self.canvas.create_oval(cx-r_cap, cy-r_cap, cx+r_cap, cy+r_cap, fill="#000000", outline="#333333")
        
        # Finger Dimple (Dynamic - initialized here, moved in update)
        self.dimple_radius = 65
        self.vfo_a_dimple = self.canvas.create_oval(0, 0, 20, 20, fill="#333333", outline="#000000")
        # Make VFO A knob interactive
        vfo_a_knob = self.canvas.create_oval(cx-r, cy-r, cx+r, cy+r, fill="", outline="", width=0)
        self.canvas.tag_bind(vfo_a_knob, "<Button-1>", lambda e: self.vfo_click("A"))
        self.canvas.tag_bind(vfo_a_knob, "<B1-Motion>", lambda e: self.vfo_drag(e, "A", cx, cy))
        self.canvas.tag_bind(vfo_a_knob, "<ButtonRelease-1>", lambda e: self.vfo_release("A"))

        # === Sub VFO B ===
        bx, by = 900, 300
        br = 65
        self.canvas.create_oval(bx-br, by-br, bx+br, by+br, fill=COLOR_KNOB_MAIN, outline="#000000", width=2)
        self.canvas.create_oval(bx-50, by-50, bx+50, by+50, outline=COLOR_KNOB_RING, width=10)
        
        # VFO B Dimple
        self.vfo_b_dimple_radius = 50
        self.vfo_b_dimple = self.canvas.create_oval(0, 0, 16, 16, fill="#333333", outline="#000000")
        # Make VFO B knob interactive
        vfo_b_knob = self.canvas.create_oval(bx-br, by-br, bx+br, by+br, fill="", outline="", width=0)
        self.canvas.tag_bind(vfo_b_knob, "<Button-1>", lambda e: self.vfo_click("B"))
        self.canvas.tag_bind(vfo_b_knob, "<B1-Motion>", lambda e: self.vfo_drag(e, "B", bx, by))
        self.canvas.tag_bind(vfo_b_knob, "<ButtonRelease-1>", lambda e: self.vfo_release("B"))
        
        # === Control Sliders (AF/RF/POWER) ===
        # AF GAIN Slider (Interactive)
        self.draw_control_slider(80, 190, "AF GAIN", "af", 0, 100)
        # SUB AF GAIN Slider (Interactive) - for VFO B
        self.draw_control_slider(80, 235, "SUB AF", "sub_af", 0, 100)
        # RF GAIN Slider (Interactive)
        self.draw_control_slider(80, 280, "RF GAIN", "rf", 0, 100)
        # POWER Level Slider (Interactive)
        self.draw_control_slider(80, 325, "POWER", "power", 0, 100)
        # Interactive knobs on right side (SHIFT/WIDTH/NOTCH)
        self.draw_interactive_knob(1100, 250, "SHIFT", "shift")
        self.draw_interactive_knob(1100, 340, "WIDTH", "width")
        self.draw_interactive_knob(1100, 430, "NOTCH", "notch")

    def draw_buttons(self):
        """Draws the keypad and mode buttons"""
        # Keypad Grid (functional)
        start_x = 620
        start_y = 220
        keypad_layout = [
            ['1', '2', '3', 'A'],
            ['4', '5', '6', 'B'],
            ['7', '8', '9', 'C'],
            ['CLR', '0', 'ENT', 'D']
        ]
        
        for row in range(4):
            for col in range(4):
                x = start_x + (col * 50)
                y = start_y + (row * 35)
                if row < 3:  # First 3 rows
                    label = keypad_layout[row][col]
                else:  # Bottom row
                    label = keypad_layout[3][col]
                
                # Create a tag for this button
                key_tag = f"key_{label}"
                btn = self.canvas.create_rectangle(x, y, x+40, y+25, fill="#333", outline="#555", width=2, tags=key_tag)
                self.canvas.create_text(x+20, y+12, text=label, fill="#aaa", font=("Arial", 10, "bold"), tags=key_tag)
                
                # Bind click event to the tag
                self.canvas.tag_bind(key_tag, "<Button-1>", lambda e, key=label: self.keypad_press(key))

        # Mode Buttons (Left of VFO)
        modes = ["LSB", "USB", "CW", "AM", "FM"]
        mx, my = 320, 220
        for mode in modes:
            # Create a tag for this button group
            mode_tag = f"mode_{mode}"
            # Button
            btn = self.canvas.create_rectangle(mx, my, mx+50, my+25, fill="#333", outline="black", tags=mode_tag)
            # Label
            self.canvas.create_text(mx+25, my+12, text=mode, fill="#aaa", font=("Arial", 9), tags=mode_tag)
            # LED Indicator (Dynamic)
            led = self.canvas.create_rectangle(mx-10, my+8, mx-4, my+18, fill=COLOR_LED_OFF, outline="", tags=mode_tag)
            self.ui_elements[f"led_{mode}"] = led
            # Bind click event to the tag
            self.canvas.tag_bind(mode_tag, "<Button-1>", lambda e, m=mode: self.mode_button_click(m))
            my += 35

        # === Antenna & Tuner Controls ===
        # ANT 1 Button
        self.draw_control_button(320, 430, "ANT 1", "ant1")
        # ANT 2 Button
        self.draw_control_button(390, 430, "ANT 2", "ant2")
        # TUNER Button
        self.draw_control_button(460, 430, "TUNER", "tuner")
        # VFO A/B Switch Button
        self.draw_control_button(540, 430, "A/B", "vfo_switch")
        # XMIT Button
        self.draw_control_button(620, 430, "XMIT", "xmit")

    def draw_control_slider(self, x, y, label, slider_id, min_val=0, max_val=100):
        """Draw an interactive slider control with tick marks"""
        slider_width = 100  # Reduced from 120
        slider_height = 14  # Reduced from 16
        
        # Label
        self.canvas.create_text(x, y-10, text=label, fill=COLOR_TEXT_LABEL, font=("Arial", 6))
        
        # Slider track (background)
        track = self.canvas.create_rectangle(
            x - slider_width//2, y - slider_height//2,
            x + slider_width//2, y + slider_height//2,
            fill="#333", outline="#555", width=2
        )
        
        # Tick marks at 25%, 50%, 75%, and 100%
        tick_positions = [0.25, 0.5, 0.75, 1.0]
        for tick_pct in tick_positions:
            tick_x = x - slider_width//2 + int(tick_pct * slider_width)
            # Short tick mark above slider
            self.canvas.create_line(
                tick_x, y - slider_height//2 - 3,
                tick_x, y - slider_height//2 - 1,
                fill="#888", width=1
            )
            # Tick mark label
            tick_label = str(int(tick_pct * 100))
            self.canvas.create_text(
                tick_x, y - slider_height//2 - 8,
                text=tick_label, fill="#666", font=("Arial", 5)
            )
        
        # Slider thumb (the moving part)
        thumb_width = 7  # Reduced from 8
        thumb = self.canvas.create_rectangle(
            x - thumb_width//2, y - slider_height//2 - 2,
            x + thumb_width//2, y + slider_height//2 + 2,
            fill="#888", outline="#aaa", width=2
        )
        
        # Value display below slider
        value_text = self.canvas.create_text(
            x, y + slider_height//2 + 10,
            text="50", fill=COLOR_DISPLAY_ON, font=("Arial", 8, "bold")
        )
        
        # Store elements
        self.ui_elements[f"{slider_id}_track"] = track
        self.ui_elements[f"{slider_id}_thumb"] = thumb
        self.ui_elements[f"{slider_id}_value"] = value_text
        self.ui_elements[f"{slider_id}_x"] = x
        self.ui_elements[f"{slider_id}_y"] = y
        self.ui_elements[f"{slider_id}_width"] = slider_width
        self.ui_elements[f"{slider_id}_min"] = min_val
        self.ui_elements[f"{slider_id}_max"] = max_val
        
        # Bind mouse events
        self.canvas.tag_bind(track, "<Button-1>", lambda e, sid=slider_id: self.slider_click(e, sid))
        self.canvas.tag_bind(track, "<B1-Motion>", lambda e, sid=slider_id: self.slider_drag(e, sid))
        self.canvas.tag_bind(thumb, "<Button-1>", lambda e, sid=slider_id: self.slider_click(e, sid))
        self.canvas.tag_bind(thumb, "<B1-Motion>", lambda e, sid=slider_id: self.slider_drag(e, sid))

    def draw_interactive_knob(self, x, y, label, knob_id):
        """Draw an interactive knob control"""
        # Knob body
        knob = self.canvas.create_oval(x-25, y-25, x+25, y+25, fill="#222", outline="#555", width=2)
        # Inner ring
        self.canvas.create_oval(x-20, y-20, x+20, y+20, outline="#444", width=1)
        # Position indicator line (dynamic)
        line = self.canvas.create_line(x, y-25, x, y-15, fill="white", width=3)
        # Label above
        self.canvas.create_text(x, y-40, text=label, fill=COLOR_TEXT_LABEL, font=("Arial", 8))
        # Value display below
        value_text = self.canvas.create_text(x, y+40, text="50", fill=COLOR_DISPLAY_ON, font=("Arial", 9, "bold"))
        
        # Store elements
        self.ui_elements[f"{knob_id}_knob"] = knob
        self.ui_elements[f"{knob_id}_line"] = line
        self.ui_elements[f"{knob_id}_value"] = value_text
        self.ui_elements[f"{knob_id}_x"] = x
        self.ui_elements[f"{knob_id}_y"] = y
        self.ui_elements[f"{knob_id}_last_angle"] = None
        
        # Bind mouse events
        self.canvas.tag_bind(knob, "<Button-1>", lambda e, kid=knob_id: self.knob_click(e, kid, x, y))
        self.canvas.tag_bind(knob, "<B1-Motion>", lambda e, kid=knob_id: self.knob_drag(e, kid, x, y))
        self.canvas.tag_bind(knob, "<ButtonRelease-1>", lambda e, kid=knob_id: self.knob_release(kid))

    def draw_filter_matrix(self):
        """Draw the APF/NR/CONTOUR filter matrix control panel"""
        # Position to the right of sliders
        base_x = 165
        base_y = 175
        
        # Title labels
        self.canvas.create_text(base_x + 25, base_y, text="APF", fill=COLOR_TEXT_LABEL, font=("Arial", 8, "bold"))
        self.canvas.create_text(base_x + 70, base_y, text="NR", fill=COLOR_TEXT_LABEL, font=("Arial", 8, "bold"))
        
        # APF filters (left column) - 250, 500, 1000, 1500, 2000
        apf_freqs = [250, 500, 1000, 1500, 2000]
        for i, freq in enumerate(apf_freqs):
            y = base_y + 15 + (i * 22)
            self.draw_filter_button(base_x, y, str(freq), f"apf_{freq}", 40)
        
        # NR filters (middle column) - 500, 1000, 1500, 2000, 3000
        nr_freqs = [500, 1000, 1500, 2000, 3000]
        for i, freq in enumerate(nr_freqs):
            y = base_y + 15 + (i * 22)
            self.draw_filter_button(base_x + 45, y, str(freq), f"nr_{freq}", 40)
        
        # NR OFF button (below NR column)
        y = base_y + 15 + (5 * 22)
        self.draw_filter_button(base_x + 45, y, "OFF", "nr_off", 40)
        
        # CONTOUR button (single button that cycles through modes)
        # Position it in the middle of the right column
        y = base_y + 15 + (2 * 22)  # Center position
        self.draw_contour_button(base_x + 90, y, "CNTR", "contour", 40)
        
        # Bottom labels
        label_y = base_y + 155
        self.canvas.create_text(base_x + 20, label_y, text="APF", fill="#666", font=("Arial", 7))
        self.canvas.create_text(base_x + 65, label_y, text="NR", fill="#666", font=("Arial", 7))
        self.canvas.create_text(base_x + 110, label_y, text="CONTOUR", fill="#666", font=("Arial", 7))

    def draw_connection_status(self):
        """Draw connection status indicator at bottom of window"""
        # Position at bottom left
        x = 120
        y = 460
        
        # SIMULATION label
        sim_label = self.canvas.create_text(
            x - 50, y - 15,
            text="SIMULATION",
            fill="#ff9900",
            font=("Arial", 8, "bold"),
            anchor="e"
        )
        
        # Status label text (to left of LED)
        status_text = self.canvas.create_text(
            x - 85, y,
            text="PORT:", fill="#ffffff",
            font=("Arial", 8),
            anchor="e"
        )
        
        # Status LED indicator
        led = self.canvas.create_oval(
            x - 75, y - 5,
            x - 65, y + 5,
            fill=COLOR_LED_OFF, outline="#444"
        )
        
        # Port name text
        port_text = self.canvas.create_text(
            x - 40, y,
            text="", fill="#aaa",
            font=("Arial", 8),
            anchor="w"
        )
        
        # Status text
        status = self.canvas.create_text(
            x + 135, y,
            text="", fill="#888",
            font=("Arial", 8),
            anchor="w"
        )
        
        # Store UI elements
        self.ui_elements["conn_port_text"] = port_text
        self.ui_elements["conn_led"] = led
        self.ui_elements["conn_status_text"] = status

    def draw_filter_button(self, x, y, label, button_id, width=40):
        """Draw a small filter matrix button"""
        button_tag = f"filter_{button_id}"
        height = 18
        
        # Button background
        btn = self.canvas.create_rectangle(
            x, y, x + width, y + height,
            fill="#2a2a2a", outline="#555", width=1,
            tags=button_tag
        )
        
        # Button label
        txt = self.canvas.create_text(
            x + width//2, y + height//2,
            text=label, fill="#888",
            font=("Arial", 7, "bold"),
            tags=button_tag
        )
        
        # LED indicator (small green square when active)
        led_size = 4
        led = self.canvas.create_rectangle(
            x + 3, y + 3,
            x + 3 + led_size, y + 3 + led_size,
            fill=COLOR_LED_OFF, outline="",
            tags=button_tag
        )
        
        # Store elements
        self.ui_elements[f"{button_id}_btn"] = btn
        self.ui_elements[f"{button_id}_led"] = led
        
        # Bind click event
        self.canvas.tag_bind(button_tag, "<Button-1>", lambda e, bid=button_id: self.filter_button_click(bid))

    def draw_contour_button(self, x, y, label, button_id, width=40):
        """Draw CONTOUR button with mode indicator text"""
        button_tag = f"filter_{button_id}"
        height = 60  # Taller to show mode text
        
        # Button background
        btn = self.canvas.create_rectangle(
            x, y, x + width, y + height,
            fill="#2a2a2a", outline="#555", width=1,
            tags=button_tag
        )
        
        # Button label at top
        txt = self.canvas.create_text(
            x + width//2, y + 12,
            text=label, fill="#888",
            font=("Arial", 7, "bold"),
            tags=button_tag
        )
        
        # Mode text (will show OFF, L-CUT, M-CUT, H-CUT)
        mode_txt = self.canvas.create_text(
            x + width//2, y + 35,
            text="OFF", fill="#ff9900",
            font=("Arial", 7, "bold"),
            tags=button_tag
        )
        
        # LED indicator (color changes with mode)
        led_size = 6
        led = self.canvas.create_rectangle(
            x + width//2 - led_size//2, y + height - 10,
            x + width//2 + led_size//2, y + height - 4,
            fill=COLOR_LED_OFF, outline="",
            tags=button_tag
        )
        
        # Store elements
        self.ui_elements[f"{button_id}_btn"] = btn
        self.ui_elements[f"{button_id}_led"] = led
        self.ui_elements[f"{button_id}_mode_txt"] = mode_txt
        
        # Bind click event
        self.canvas.tag_bind(button_tag, "<Button-1>", lambda e, bid=button_id: self.filter_button_click(bid))

    def draw_control_button(self, x, y, label, button_id):
        """Draw an interactive button control"""
        # Create a tag for this button group
        button_tag = f"btn_{button_id}"
        
        # Button rectangle
        btn = self.canvas.create_rectangle(x, y, x+60, y+30, fill="#333", outline="#666", width=2, tags=button_tag)
        # Button label
        txt = self.canvas.create_text(x+30, y+15, text=label, fill="#aaa", font=("Arial", 10, "bold"), tags=button_tag)
        # LED indicator
        led = self.canvas.create_oval(x+5, y+5, x+12, y+12, fill=COLOR_LED_OFF, outline="", tags=button_tag)
        
        # Store elements
        self.ui_elements[f"{button_id}_btn"] = btn
        self.ui_elements[f"{button_id}_led"] = led
        
        # Bind click event to the tag (covers all elements)
        self.canvas.tag_bind(button_tag, "<Button-1>", lambda e, bid=button_id: self.button_click(bid))

    def slider_click(self, event, slider_id):
        """Handle slider click"""
        self.slider_drag(event, slider_id)

    def slider_drag(self, event, slider_id):
        """Handle slider dragging to adjust value"""
        # Get slider parameters
        x = self.ui_elements[f"{slider_id}_x"]
        slider_width = self.ui_elements[f"{slider_id}_width"]
        min_val = self.ui_elements[f"{slider_id}_min"]
        max_val = self.ui_elements[f"{slider_id}_max"]
        
        # Calculate value from mouse position
        left_edge = x - slider_width//2
        right_edge = x + slider_width//2
        
        # Clamp mouse position to slider bounds
        mouse_x = max(left_edge, min(right_edge, event.x))
        
        # Calculate percentage (0.0 to 1.0)
        pct = (mouse_x - left_edge) / slider_width
        
        # Calculate value
        value = int(min_val + pct * (max_val - min_val))
        value = max(min_val, min(max_val, value))
        
        # Update the appropriate control
        if slider_id == "af":
            self.af_gain = value
        elif slider_id == "sub_af":
            self.sub_af_gain = value
        elif slider_id == "rf":
            self.rf_gain = value
        elif slider_id == "power":
            self.power_level = value
    def knob_click(self, event, knob_id, center_x, center_y):
        """Handle knob click - initialize angle tracking"""
        pass  # Angle tracking starts on first drag

    def knob_drag(self, event, knob_id, center_x, center_y):
        """Handle knob dragging to adjust value"""
        # Calculate angle from center
        dx = event.x - center_x
        dy = event.y - center_y
        angle = math.atan2(dy, dx)
        
        # Get the last angle for this knob
        last_angle = self.ui_elements.get(f"{knob_id}_last_angle")
        
        # If we have a previous angle, calculate the delta
        if last_angle is not None:
            # Calculate angle difference
            delta_angle = angle - last_angle
            
            # Handle wrap-around (crossing from +π to -π or vice versa)
            if delta_angle > math.pi:
                delta_angle -= 2 * math.pi
            elif delta_angle < -math.pi:
                delta_angle += 2 * math.pi
            
            # Convert angle delta to value adjustment
            # ~0.1 radians = ~3 units
            value_delta = (delta_angle / (math.pi * 0.1)) * 3.0
            
            # Apply the adjustment
            if knob_id == "shift":
                self.shift = max(0, min(100, self.shift + value_delta))
            elif knob_id == "width":
                self.width = max(0, min(100, self.width + value_delta))
            elif knob_id == "notch":
                self.notch = max(0, min(100, self.notch + value_delta))
        
        # Store current angle for next drag event
        self.ui_elements[f"{knob_id}_last_angle"] = angle

    def knob_release(self, knob_id):
        """Reset angle tracking when mouse button is released"""
        self.ui_elements[f"{knob_id}_last_angle"] = None

    def filter_button_click(self, button_id):
        """Handle filter matrix button clicks - mutually exclusive within each column"""
        if button_id == "nr_off":
            # Turn off all NR filters
            self.nr_off = True
            for freq in self.nr_filters:
                self.nr_filters[freq] = False
            self.send_nr_to_radio(None)
        elif button_id == "contour":
            # Cycle through CONTOUR modes: 0=OFF, 1=Low-Cut, 2=Mid-Cut, 3=High-Cut
            self.contour_mode = (self.contour_mode + 1) % 4
        elif button_id.startswith("apf_"):
            # APF filters are mutually exclusive - only one can be active
            freq = int(button_id.split('_')[1])
            # First turn off all APF filters
            for f in self.apf_filters:
                self.apf_filters[f] = False
            # Then turn on the selected one
            self.apf_filters[freq] = True
            self.send_apf_to_radio(freq)
        elif button_id.startswith("nr_"):
            # NR filters are mutually exclusive - only one can be active
            freq = int(button_id.split('_')[1])
            # First turn off all NR filters
            for f in self.nr_filters:
                self.nr_filters[f] = False
            # Then turn on the selected one
            self.nr_filters[freq] = True
            self.nr_off = False
            self.send_nr_to_radio(freq)

    def button_click(self, button_id):
        """Handle button clicks"""
        if button_id == "ant1":
            self.antenna = 1
            self.send_antenna_to_radio(1)
        elif button_id == "ant2":
            self.antenna = 2
            self.send_antenna_to_radio(2)
        elif button_id == "tuner":
            self.tuner_active = not self.tuner_active
            self.send_tuner_to_radio(self.tuner_active)
        elif button_id == "vfo_switch":
            # Toggle between VFO A and B
            self.active_vfo = "B" if self.active_vfo == "A" else "A"
            self.send_vfo_select_to_radio(self.active_vfo)
        elif button_id == "xmit":
            # Toggle transmit
            self.transmitting = not self.transmitting
            if self.transmitting:
                self.tx_meter_hold_until = time.time() + 0.40
            else:
                # Return to RX behavior immediately when the app unkeys the radio.
                self.radio_tx_active = False
                self.tx_meter_hold_until = 0.0
            self.send_ptt_to_radio(self.transmitting)

    def mode_button_click(self, mode):
        """Handle mode button clicks"""
        # Set mode for the active VFO
        if self.active_vfo == "A":
            self.mode = mode
            self.send_mode_to_radio(mode, "A")
        else:
            self.mode_vfo_b = mode
            self.send_mode_to_radio(mode, "B")

    def keypad_press(self, key):
        """Handle keypad button press"""
        if key in '0123456789':
            # Add digit to buffer
            if len(self.freq_entry_buffer) < 8:  # Max 8 digits (e.g., 14320000 for 14.320.00)
                self.freq_entry_buffer += key
                self.freq_entry_mode = True
        elif key == 'CLR':
            # Clear buffer
            self.freq_entry_buffer = ""
            self.freq_entry_mode = False
        elif key == 'ENT':
            # Enter frequency
            if len(self.freq_entry_buffer) >= 4:  # At least 4 digits (e.g., 1432 for 14.32)
                self.set_frequency_from_entry()
            self.freq_entry_buffer = ""
            self.freq_entry_mode = False
        elif key == '.':  # Period for decimal point (optional)
            pass  # Ignore, we format automatically

    def set_frequency_from_entry(self):
        """Parse entry buffer and set frequency"""
        try:
            # Pad with zeros if needed
            entry = self.freq_entry_buffer.ljust(8, '0')
            
            # Format as XX.XXX.XX (e.g., 14320000 -> 114.320.00)
            formatted = f"{entry[0:2]}.{entry[2:5]}.{entry[5:7]}"
            
            # Remove leading zero if present
            if formatted.startswith("0"):
                formatted = formatted[1:]
            
            # Validate frequency range (1.8-30 MHz)
            freq_mhz = float(entry[0:2] + "." + entry[2:])
            if 1.8 <= freq_mhz <= 30.0:
                if self.active_vfo == "A":
                    self.frequency = formatted
                    # Set appropriate mode for this frequency
                    self.set_mode_for_frequency("A")
                    # Send to radio
                    self.send_frequency_to_radio("A")
                    self.send_mode_to_radio(self.mode, "A")
                else:
                    self.frequency_vfo_b = formatted
                    # Set appropriate mode for this frequency
                    self.set_mode_for_frequency("B")
                    # Send to radio
                    self.send_frequency_to_radio("B")
                    self.send_mode_to_radio(self.mode_vfo_b, "B")
            else:
                print(f"Frequency {freq_mhz} MHz out of valid range (1.8-30 MHz)")
        except Exception as e:
            print(f"Frequency entry error: {e}")
            import traceback
            traceback.print_exc()

    def vfo_click(self, vfo):
        """Handle VFO knob click - set as active VFO"""
        self.active_vfo = vfo
        # Don't reset angle here - let it continue from where it was
        # Angle will be reset on ButtonRelease

    def vfo_drag(self, event, vfo, center_x, center_y):
        """Handle VFO knob dragging to tune frequency"""
        # Calculate angle from center
        dx = event.x - center_x
        dy = event.y - center_y
        angle = math.atan2(dy, dx)
        
        # Get the last angle for this VFO
        if vfo == "A":
            last_angle = self.vfo_a_last_angle
        else:
            last_angle = self.vfo_b_last_angle
        
        # If we have a previous angle, calculate the delta
        if last_angle is not None:
            # Calculate angle difference
            delta_angle = angle - last_angle
            
            # Handle wrap-around (crossing from +π to -π or vice versa)
            if delta_angle > math.pi:
                delta_angle -= 2 * math.pi
            elif delta_angle < -math.pi:
                delta_angle += 2 * math.pi
            
            # Convert angle delta to frequency adjustment
            # Small movements: ~0.1 radians = ~1 kHz (tunable sensitivity)
            freq_offset = (delta_angle / (math.pi * 0.2)) * 1.0  # kHz
            
            # Apply the adjustment
            self.adjust_frequency(vfo, freq_offset)
        
        # Store current angle for next drag event
        if vfo == "A":
            self.vfo_a_last_angle = angle
        else:
            self.vfo_b_last_angle = angle

    def vfo_release(self, vfo):
        """Reset angle tracking when mouse button is released"""
        if vfo == "A":
            self.vfo_a_last_angle = None
        else:
            self.vfo_b_last_angle = None

    def cat_write(self, cmd):
        """Send a CAT command with optional debug logging."""
        if self.serial_port is None:
            return
        with self.serial_lock:
            self.serial_port.write(cmd)
        cat_debug_log("TX", cmd)

    def cat_write_read(self, cmd, response_len=0, read_delay_s=None):
        """Send CAT command and optionally read a fixed-length response."""
        if self.serial_port is None:
            return b""

        if read_delay_s is None:
            read_delay_s = CAT_COMMAND_DELAY_S

        with self.serial_lock:
            self.serial_port.reset_input_buffer()
            self.serial_port.write(cmd)
            cat_debug_log("TX", cmd)
            time.sleep(read_delay_s)
            if response_len <= 0:
                return b""
            data = self.serial_port.read(response_len)
        if data:
            cat_debug_log("RX", data)
        return data

    def cat_read_frequency(self, opcode=None, status_param=None):
        """Send a frequency poll and collect the response via blocking read.
        
        Try opcode 0x03 (simple read) first; fall back to 0x10 0x02 (Status Update Current Data).
        Status Update returns 16-byte record with frequency at bytes 0-3.
        """
        if self.serial_port is None:
            return b""

        if opcode is None:
            opcode = CAT_READ_OPCODE

        # For opcode 0x10 (Status Update), byte 4 is parameter.
        if opcode == 0x10:
            param = CAT_STATUS_UPDATE_PARAM if status_param is None else status_param
            response_len_map = {
                0x01: 1,
                0x02: 16,
                0x03: 32,
                0x04: 16,
            }
            response_len = response_len_map.get(param, 16)
            cmd_freq = bytearray([0x00, 0x00, 0x00, param, 0x10])
        else:
            response_len = 5  # Standard 5-byte frequency response
            cmd_freq = bytearray([0x00, 0x00, 0x00, 0x00, opcode])

        with self.serial_lock:
            self.serial_port.reset_input_buffer()
            self.serial_port.write(cmd_freq)
            cat_debug_log("TX", cmd_freq)
            time.sleep(CAT_FREQ_READ_DELAY_S)  # let radio transmit its response

            # Blocking read: accumulate bytes within the deadline.
            data = b""
            deadline = time.time() + 1.5
            while len(data) < response_len and time.time() < deadline:
                chunk = self.serial_port.read(response_len - len(data))
                if chunk:
                    data += chunk

        if data:
            if opcode == 0x10:
                cat_debug_log(f"RX (opcode 0x{opcode:02x}, param 0x{param:02x})", data)
            else:
                cat_debug_log(f"RX (opcode 0x{opcode:02x})", data)
            
            # DEBUG: Show raw byte analysis for opcode 0x10
            if CAT_DEBUG and opcode == 0x10 and len(data) >= 4:
                print(f"  [DEBUG] Status Update raw bytes[0:4]: {data[0]:02X} {data[1]:02X} {data[2]:02X} {data[3]:02X}")
                print(f"  [DEBUG] Trying to match expected 18.170.22 MHz = BCD: 01 81 70 22")
                # Try interpreting bytes at different positions
                for i in range(max(0, len(data)-4)):
                    test_bytes = data[i:i+4]
                    if len(test_bytes) == 4:
                        # Check if valid BCD
                        valid_bcd = all(((b >> 4) & 0x0F) <= 9 and (b & 0x0F) <= 9 for b in test_bytes)
                        if valid_bcd:
                            bcd_str = "".join(f"{b:02x}" for b in test_bytes)
                            freq_10hz = int(bcd_str)
                            freq_mhz = freq_10hz / 100000.0
                            print(f"  [DEBUG]   Bytes[{i}:{i+4}]: {' '.join(f'{b:02X}' for b in test_bytes)} → {freq_mhz:.5f} MHz")
        
        return data


    def connect_serial_with_profile(self, port_name, baud_rate, timeout_seconds=0.5):
        """Try known serial framing profiles and keep the first that yields CAT data."""
        last_error = None

        for bytesize, parity, stopbits, profile_name in SERIAL_PROFILES:
            try:
                candidate = build_serial_connection(
                    port_name,
                    baud_rate,
                    timeout_seconds=timeout_seconds,
                    bytesize=bytesize,
                    parity=parity,
                    stopbits=stopbits,
                )
                self.serial_port = candidate
                self.serial_profile_name = profile_name
                print(f"Trying serial profile {profile_name}...")

                # Probe known direct frequency read opcodes and status-update variants.
                probe_succeeded = False
                probe_targets = [
                    (0x03, None),
                    (0x00, None),
                    (0x10, 0x03),  # VFO-A/VFO-B 32-byte data per manual
                    (0x10, 0x02),  # Current operating data 16-byte record
                ]
                for opcode, status_param in probe_targets:
                    probe = self.cat_read_frequency(opcode=opcode, status_param=status_param)
                    if not probe:
                        if opcode == 0x10:
                            print(
                                f"CAT probe: 0 bytes with opcode 0x{opcode:02X}/0x{status_param:02X} "
                                f"on {profile_name}"
                            )
                        else:
                            print(f"CAT probe: 0 bytes with opcode 0x{opcode:02X} on {profile_name}")
                        continue

                    if has_valid_frequency_in_payload(probe, opcode, status_param, self.frequency):
                        self.cat_read_opcode_working = opcode
                        self.cat_read_status_param_working = status_param
                        self.cat_read_enabled = True
                        if opcode == 0x10:
                            print(
                                f"CAT probe succeeded with profile {profile_name} using "
                                f"opcode 0x{opcode:02X}/0x{status_param:02X}"
                            )
                        else:
                            print(
                                f"CAT probe succeeded with profile {profile_name} using "
                                f"opcode 0x{opcode:02X}"
                            )
                        probe_succeeded = True
                        break

                    if opcode == 0x10:
                        print(
                            f"CAT probe: {len(probe)} bytes with opcode 0x{opcode:02X}/0x{status_param:02X} "
                            f"on {profile_name} — no valid freq decoded"
                        )
                    else:
                        print(
                            f"CAT probe: {len(probe)} bytes with opcode 0x{opcode:02X} "
                            f"on {profile_name} — no valid freq decoded"
                        )

                if probe_succeeded:
                    return

                # Optional diagnostic only: check if 0x10 returns data, but do not treat as frequency lock.
                if CAT_USE_STATUS_UPDATE_FOR_FREQ:
                    probe = self.cat_read_frequency(opcode=0x10)
                    if probe:
                        print(
                            f"CAT status probe: {len(probe)} bytes with opcode 0x10 on {profile_name} "
                            f"(not used for frequency lock)"
                        )

                candidate.close()
                self.serial_port = None
            except Exception as e:
                last_error = e
                if self.serial_port is not None:
                    try:
                        self.serial_port.close()
                    except Exception:
                        pass
                    self.serial_port = None

        # Fallback: keep default profile connected for TX-only operation.
        if self.serial_port is None:
            if last_error is not None:
                print(f"Profile probes failed, falling back to default profile: {last_error}")
            self.serial_port = build_serial_connection(port_name, baud_rate, timeout_seconds=timeout_seconds)
            self.serial_profile_name = "default"
            self.cat_read_opcode_working = None
            self.cat_read_status_param_working = None
            self.cat_read_enabled = False
            print("Connected with default profile (TX-only: CAT readback unavailable)")

    def send_frequency_to_radio(self, vfo="A"):
        """Send frequency command to radio via serial"""
        if MOCK_MODE or self.serial_port is None:
            return
        
        try:
            # Get the frequency to send
            freq_str = self.frequency if vfo == "A" else self.frequency_vfo_b
            bcd_bytes = encode_frequency_to_cat_bytes(freq_str, lsb_first=CAT_FREQ_LSB_FIRST)

            # FT-1000MP commands:
            # - Main VFO-A frequency: 0x0A
            # - Sub  VFO-B frequency: 0x8A
            opcode = 0x0A if vfo == "A" else 0x8A
            cmd = bytearray([bcd_bytes[0], bcd_bytes[1], bcd_bytes[2], bcd_bytes[3], opcode])
            self.cat_write(cmd)
        except Exception as e:
            print(f"Error sending frequency to radio: {e}")
            import traceback
            traceback.print_exc()

    def send_mode_to_radio(self, mode, vfo="A"):
        """Send mode command to radio via serial"""
        if MOCK_MODE or self.serial_port is None:
            return
        
        try:
            # Mode map for FT-1000MP
            mode_map = {
                "LSB": 0x00,
                "USB": 0x01,
                "CW": 0x02,
                "AM": 0x04,
                "FM": 0x06,
            }
            mode_byte = mode_map.get(mode, 0x01)

            # FT-1000MP command: MODE select (0x0C)
            cmd = bytearray([0x00, 0x00, 0x00, mode_byte, 0x0C])
            self.cat_write(cmd)
            # Avoid immediate bounce from stale status frames right after local writes.
            self.mode_sync_block_until = time.time() + 1.0
        except Exception as e:
            print(f"Error sending mode to radio: {e}")
            import traceback
            traceback.print_exc()

    def send_nr_to_radio(self, nr_freq):
        """Send EDSP Noise Reduction setting via opcode 0x4A.
        P4 0x00 = OFF; 0x01-0x0A = NR levels 1-10.
        """
        if MOCK_MODE or self.serial_port is None:
            return

        try:
            if nr_freq is None:
                level = 0x00  # NR OFF
            else:
                # Map UI pseudo-frequency labels to NR levels 1-10
                freq_to_level = {250: 2, 500: 2, 1000: 4, 1500: 6, 2000: 8, 3000: 10}
                level = freq_to_level.get(nr_freq, 5)
            cmd = bytearray([0x00, 0x00, 0x00, level, 0x4A])
            self.cat_write(cmd)
        except Exception as e:
            print(f"Error sending NR to radio: {e}")

    def send_apf_to_radio(self, apf_freq):
        """Send EDSP Audio Peak Filter (APF) command via opcode 0x4C.
        P4 0x00 = OFF; 0x01+ = ON (center tracks beat note automatically).
        Note: 0x4B is Audio Notch (DNF); APF is 0x4C per manual ordering.
        """
        if MOCK_MODE or self.serial_port is None:
            return

        try:
            p1 = 0x01 if apf_freq is not None else 0x00
            cmd = bytearray([0x00, 0x00, 0x00, p1, 0x4C])
            self.cat_write(cmd)
        except Exception as e:
            print(f"Error sending APF to radio: {e}")

    def send_antenna_to_radio(self, antenna):
        """Send antenna select via opcode 0x81.
        P4 encodes antenna in bits 2-3 (matching the status record decode):
          ANT1 = 0x00 (bits 2-3 = 00), ANT2 = 0x04 (bit 2 set).
        Tuner state is OR'd in if currently active.
        """
        if MOCK_MODE or self.serial_port is None:
            return

        try:
            p4 = 0x04 if antenna == 2 else 0x00
            if self.tuner_active:
                p4 |= 0x01  # bit 0 = AT-AT tuner engaged
            self.cat_write(bytearray([0x00, 0x00, 0x00, p4, 0x81]))
        except Exception as e:
            print(f"Error sending antenna to radio: {e}")

    def send_tuner_to_radio(self, active):
        """Toggle the AT-AT antenna tuner via opcode 0x81.
        Bit 0 in P4 = tuner engaged; antenna selection is preserved.
        """
        if MOCK_MODE or self.serial_port is None:
            return

        try:
            p4 = 0x04 if self.antenna == 2 else 0x00
            if active:
                p4 |= 0x01  # bit 0 = tuner ON
            self.cat_write(bytearray([0x00, 0x00, 0x00, p4, 0x81]))
        except Exception as e:
            print(f"Error sending tuner state to radio: {e}")

    def send_ptt_to_radio(self, transmit):
        """Key/un-key the transmitter via opcode 0x0F.

        FT-1000MP native CAT uses:
        - P4 = 0x01, opcode 0x0F -> PTT ON
        - P4 = 0x00, opcode 0x0F -> PTT OFF
        """
        if MOCK_MODE or self.serial_port is None:
            return

        try:
            p4 = 0x01 if transmit else 0x00
            self.cat_write(bytearray([0x00, 0x00, 0x00, p4, 0x0F]))
        except Exception as e:
            print(f"Error sending PTT to radio: {e}")

    def send_vfo_select_to_radio(self, vfo):
        """Select active VFO on radio using opcode 0x05."""
        if MOCK_MODE or self.serial_port is None:
            return

        try:
            v = 0x00 if vfo == "A" else 0x01
            self.cat_write(bytearray([0x00, 0x00, 0x00, v, 0x05]))
        except Exception as e:
            print(f"Error selecting VFO on radio: {e}")

    def read_meter_from_radio(self):
        """Read main S-meter using opcode F7."""
        if self.serial_port is None:
            return None

        try:
            data = self.cat_write_read(
                bytearray([0x00, 0x00, 0x00, 0x00, 0xF7]),
                response_len=5,
                read_delay_s=CAT_METER_READ_DELAY_S,
            )
            if len(data) >= 1:
                return data[0]
        except Exception as e:
            print(f"Error reading meter from radio: {e}")
        return None

    def read_panel_meter(self, selector):
        """Read panel/meter value using opcode F7 and selector byte M."""
        if self.serial_port is None:
            return None

        try:
            data = self.cat_write_read(
                bytearray([0x00, 0x00, 0x00, selector, 0xF7]),
                response_len=5,
                read_delay_s=CAT_METER_READ_DELAY_S,
            )
            if len(data) >= 1:
                return data[0]
        except Exception as e:
            print(f"Error reading panel selector 0x{selector:02X}: {e}")
        return None

    def adjust_frequency(self, vfo, delta_khz):
        """Adjust frequency by delta in kHz"""
        try:
            if vfo == "A":
                freq_str = self.frequency.replace(".", "")
                # Parse as integer in 10Hz units (e.g., "1432000" = 14.32000 MHz)
                freq_10hz = int(freq_str)
                # Convert to kHz: 1432000 → 14320.0 kHz
                freq_khz = freq_10hz / 100.0
                freq_khz += delta_khz
                # Limit to ham bands (1.8 - 30 MHz)
                freq_khz = max(1800, min(30000, freq_khz))
                # Convert back to 10Hz units
                freq_10hz = int(freq_khz * 100)
                # Format: pad to at least 6 digits (minimum 1.800 MHz = 180000)
                freq_str = f"{freq_10hz:06d}"
                # Handle different lengths
                if len(freq_str) == 6:  # 1-9 MHz: format as X.XXX.XX
                    self.frequency = f"{freq_str[0]}.{freq_str[1:4]}.{freq_str[4:6]}"
                elif len(freq_str) == 7:  # 10-29 MHz: format as XX.XXX.XX
                    self.frequency = f"{freq_str[0:2]}.{freq_str[2:5]}.{freq_str[5:7]}"
                else:  # 30 MHz: format as XX.XXX.XX
                    self.frequency = f"{freq_str[0:2]}.{freq_str[2:5]}.{freq_str[5:7]}"
                # Set appropriate mode for this frequency
                self.set_mode_for_frequency("A")
            else:
                freq_str = self.frequency_vfo_b.replace(".", "")
                freq_10hz = int(freq_str)
                freq_khz = freq_10hz / 100.0
                freq_khz += delta_khz
                freq_khz = max(1800, min(30000, freq_khz))
                freq_10hz = int(freq_khz * 100)
                freq_str = f"{freq_10hz:06d}"
                if len(freq_str) == 6:
                    self.frequency_vfo_b = f"{freq_str[0]}.{freq_str[1:4]}.{freq_str[4:6]}"
                elif len(freq_str) == 7:
                    self.frequency_vfo_b = f"{freq_str[0:2]}.{freq_str[2:5]}.{freq_str[5:7]}"
                else:
                    self.frequency_vfo_b = f"{freq_str[0:2]}.{freq_str[2:5]}.{freq_str[5:7]}"
                # Set appropriate mode for this frequency
                self.set_mode_for_frequency("B")
            
            # Send to radio if not in mock mode
            if vfo == "A":
                self.send_frequency_to_radio("A")
                self.send_mode_to_radio(self.mode, "A")
            else:
                self.send_frequency_to_radio("B")
                self.send_mode_to_radio(self.mode_vfo_b, "B")
        except Exception as e:
            print(f"Frequency adjustment error: {e}")
            import traceback
            traceback.print_exc()

    def init_dynamic_display(self):
        """Creates the text and meter bars that change"""
        
        # === VFO A Display ===
        # Active Text
        self.ui_elements["freq_a"] = self.canvas.create_text(640, 75, text=self.frequency, fill=COLOR_DISPLAY_ON, font=("Courier", 48, "bold"), anchor="e")
        self.ui_elements["mode_a"] = self.canvas.create_text(360, 40, text=self.mode, fill="#00ff00", font=("Arial", 12, "bold"))
        self.canvas.create_text(640, 35, text="VFO A", fill="#cc5500", font=("Arial", 10, "bold"))

        # === Antenna Display (placed right-of-center, clear of VFO A/B labels) ===
        self.ui_elements["antenna_display"] = self.canvas.create_text(780, 35, text="ANT 1", fill=COLOR_DISPLAY_ON, font=("Arial", 10, "bold"))

        # === VFO B Display ===
        self.ui_elements["freq_b"] = self.canvas.create_text(1120, 75, text=self.frequency_vfo_b, fill=COLOR_DISPLAY_ON, font=("Courier", 48, "bold"), anchor="e")
        self.ui_elements["mode_b"] = self.canvas.create_text(920, 40, text=self.mode_vfo_b, fill="#00ff00", font=("Arial", 12, "bold"))
        self.canvas.create_text(1120, 35, text="VFO B", fill="#cc5500", font=("Arial", 10, "bold"))

        # === Meters ===
        # Labels for all meters - positioned on left side
        self.canvas.create_text(70, 30, text="RX", fill="#888888", font=("Arial", 9, "bold"), anchor="w")
        self.canvas.create_text(70, 55, text="PO", fill="#888888", font=("Arial", 9, "bold"), anchor="w")
        self.canvas.create_text(70, 80, text="SWR", fill="#888888", font=("Arial", 9, "bold"), anchor="w")
        
        # === RX Signal Strength Meter (S-Meter) - 25 segments ===
        self.meter_segments = []
        meter_x_start = 100
        meter_y = 30
        for i in range(25):
            color = "#00ff00" # Green
            if i > 17: color = "#ffff00" # Yellow
            if i > 21: color = "#ff0000" # Red
            
            seg = self.canvas.create_rectangle(
                meter_x_start + (i*7), meter_y, 
                meter_x_start + (i*7) + 5, meter_y + 8, 
                fill="#222", outline=""
            )
            self.meter_segments.append({'id': seg, 'on_color': color})
        
        # === Power Output Meter (25 segments) ===
        self.power_meter_segments = []
        power_meter_y = 55
        for i in range(25):
            color = "#00ff00" # Green
            if i > 17: color = "#ffff00" # Yellow
            if i > 21: color = "#ff0000" # Red
            
            seg = self.canvas.create_rectangle(
                meter_x_start + (i*7), power_meter_y, 
                meter_x_start + (i*7) + 5, power_meter_y + 8, 
                fill="#222", outline=""
            )
            self.power_meter_segments.append({'id': seg, 'on_color': color})
        
        # === SWR Meter (25 segments) ===
        self.swr_meter_segments = []
        swr_meter_y = 80
        for i in range(25):
            color = "#00ff00" # Green for low SWR
            if i > 8: color = "#ffff00" # Yellow
            if i > 15: color = "#ff0000" # Red for high SWR
            
            seg = self.canvas.create_rectangle(
                meter_x_start + (i*7), swr_meter_y, 
                meter_x_start + (i*7) + 5, swr_meter_y + 8, 
                fill="#222", outline=""
            )
            self.swr_meter_segments.append({'id': seg, 'on_color': color})

    def load_settings(self):
        """Load saved settings from JSON file"""
        try:
            if self.settings_file.exists():
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                    self.frequency = settings.get('frequency_a', "14.320.00")
                    self.frequency_vfo_b = settings.get('frequency_b', "18.120.00")
                    self.mode = settings.get('mode_a', "USB")
                    self.mode_vfo_b = settings.get('mode_b', "LSB")
                    self.af_gain = settings.get('af_gain', 50)
                    self.sub_af_gain = settings.get('sub_af_gain', 50)
                    self.rf_gain = settings.get('rf_gain', 80)
                    self.power_level = settings.get('power_level', 100)
                    print(f"Loaded settings from {self.settings_file}")
        except Exception as e:
            print(f"Error loading settings: {e}")

    def save_settings(self):
        """Save current settings to JSON file"""
        try:
            settings = {
                'frequency_a': self.frequency,
                'frequency_b': self.frequency_vfo_b,
                'mode_a': self.mode,
                'mode_b': self.mode_vfo_b,
                'af_gain': self.af_gain,
                'sub_af_gain': self.sub_af_gain,
                'rf_gain': self.rf_gain,
                'power_level': self.power_level,
            }
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
            print(f"✓ Settings saved to {self.settings_file}")
            self.show_status_message("Settings Saved", 2000)
        except Exception as e:
            print(f"Error saving settings: {e}")
    
    def keyboard_frequency_adjust(self, delta_khz):
        """Adjust frequency using keyboard (arrow keys)"""
        if self.freq_entry_mode:
            return  # Don't adjust if in frequency entry mode
        self.adjust_frequency(self.active_vfo, delta_khz)
    
    def switch_vfo(self):
        """Toggle between VFO A and B (Ctrl+Left)"""
        self.active_vfo = "B" if self.active_vfo == "A" else "A"
        self.send_vfo_select_to_radio(self.active_vfo)
    
    def cycle_mode(self):
        """Cycle through modes (Ctrl+M)"""
        modes = ["LSB", "USB", "CW", "AM", "FM"]
        if self.active_vfo == "A":
            current_idx = modes.index(self.mode) if self.mode in modes else 0
            self.mode = modes[(current_idx + 1) % len(modes)]
            self.send_mode_to_radio(self.mode, "A")
        else:
            current_idx = modes.index(self.mode_vfo_b) if self.mode_vfo_b in modes else 0
            self.mode_vfo_b = modes[(current_idx + 1) % len(modes)]
            self.send_mode_to_radio(self.mode_vfo_b, "B")

    def store_memory(self, channel):
        """Store current frequency and mode to memory channel (Alt+Shift+0-9)"""
        if 0 <= channel < 10:
            self.memory_channels[channel] = {
                'freq_a': self.frequency,
                'mode_a': self.mode,
                'freq_b': self.frequency_vfo_b,
                'mode_b': self.mode_vfo_b,
            }
            self.selected_memory = channel
            print(f"Stored current frequencies to memory {channel}")
            self.show_status_message(f"Memory {channel} Stored", 1500)
    
    def recall_memory(self, channel):
        """Recall frequency and mode from memory channel (Alt+0-9)"""
        if 0 <= channel < 10:
            mem = self.memory_channels[channel]
            self.frequency = mem['freq_a']
            self.mode = mem['mode_a']
            self.frequency_vfo_b = mem['freq_b']
            self.mode_vfo_b = mem['mode_b']
            self.selected_memory = channel
            self.send_frequency_to_radio("A")
            self.send_mode_to_radio(self.mode, "A")
            print(f"Recalled memory channel {channel}: {self.frequency} {self.mode}")
            self.show_status_message(f"Memory {channel}: {self.frequency} {self.mode}", 2000)

    def toggle_split(self):
        """Toggle Split Frequency mode (Ctrl+')"""
        self.split_enabled = not self.split_enabled
        if self.split_enabled:
            print(f"Split mode ON: TX on {self.frequency} / RX on {self.frequency_vfo_b}")
            self.show_status_message("Split Mode ON", 2000)
        else:
            print("Split mode OFF")
            self.show_status_message("Split Mode OFF", 1500)

    def toggle_help(self):
        """Toggle help display (Ctrl+H)"""
        self.show_help = not self.show_help

    def show_status_message(self, message, duration_ms=2000):
        """Show a temporary status message on screen"""
        # Store message and timestamp
        self.status_message = message
        self.status_message_until = time.time() + (duration_ms / 1000.0)

    def start_api_server(self):
        """Start the HTTP API server in a background thread"""
        def run_server():
            try:
                # Set the radio app reference for the handler
                RadioAPIHandler.radio_app = self
                
                # Create and start server
                self.api_server = ThreadingHTTPServer((HTTP_API_HOST, HTTP_API_PORT), RadioAPIHandler)
                print(f"✓ HTTP API server started on http://{HTTP_API_HOST}:{HTTP_API_PORT}")
                print(f"  Example: curl http://{HTTP_API_HOST}:{HTTP_API_PORT}/api/status")
                
                # Run server (blocks in this thread)
                self.api_server.serve_forever()
            except Exception as e:
                print(f"Error starting HTTP API server: {e}")
                self.api_server = None
        
        # Start in background thread
        api_thread = threading.Thread(target=run_server, daemon=True)
        api_thread.start()

    def on_close(self):
        """Gracefully stop background threads and persist current settings."""
        self.running = False
        self.save_settings()

        if self.api_server is not None:
            try:
                self.api_server.shutdown()
                self.api_server.server_close()
            except Exception as e:
                print(f"Error stopping HTTP API server: {e}")
            finally:
                self.api_server = None

        if self.serial_port is not None:
            try:
                self.serial_port.close()
            except Exception:
                pass
            finally:
                self.serial_port = None

        self.destroy()

    def animate(self):
        """Main UI Update Loop"""
        try:
            # Clear help overlay from previous frame
            self.canvas.delete("help_overlay")
            self.update_face()
        except Exception as e:
            print(f"UI Error: {e}")
        
        self.after(ANIMATION_LOOP_MS, self.animate)

    def update_face(self):
        # 1. Update Frequency A (with caching for optimization)
        freq_a_color = COLOR_DISPLAY_RED if (self.transmitting and self.active_vfo == "A") else COLOR_DISPLAY_ON
        if self.active_vfo != "A": freq_a_color = "#885500" # Dim if inactive
        
        # Show entry buffer if in entry mode and VFO A is active
        freq_a_display = self.frequency
        if self.freq_entry_mode and self.active_vfo == "A":
            # Format partial entry for display
            entry_padded = self.freq_entry_buffer.ljust(8, '_')
            freq_a_display = f"{entry_padded[0:2]}.{entry_padded[2:5]}.{entry_padded[5:7]}"
            if freq_a_display.startswith("_"):
                freq_a_display = " " + freq_a_display[1:]
        
        # Only update if changed (optimization)
        if freq_a_display != self.cached_freq_a:
            self.canvas.itemconfig(self.ui_elements["freq_a"], text=freq_a_display, fill=freq_a_color)
            self.cached_freq_a = freq_a_display
        else:
            # Still update color in case it changed to/from red
            self.canvas.itemconfig(self.ui_elements["freq_a"], fill=freq_a_color)
        
        # Only update mode if changed
        if self.mode != self.cached_mode_a:
            self.canvas.itemconfig(self.ui_elements["mode_a"], text=self.mode)
            self.cached_mode_a = self.mode

        # 2. Update Frequency B (with caching for optimization)
        freq_b_color = COLOR_DISPLAY_RED if (self.transmitting and self.active_vfo == "B") else COLOR_DISPLAY_ON
        if self.active_vfo != "B": freq_b_color = "#885500"
        
        # Show entry buffer if in entry mode and VFO B is active
        freq_b_display = self.frequency_vfo_b
        if self.freq_entry_mode and self.active_vfo == "B":
            entry_padded = self.freq_entry_buffer.ljust(8, '_')
            freq_b_display = f"{entry_padded[0:2]}.{entry_padded[2:5]}.{entry_padded[5:7]}"
            if freq_b_display.startswith("_"):
                freq_b_display = " " + freq_b_display[1:]
        
        # Only update if changed (optimization)
        if freq_b_display != self.cached_freq_b:
            self.canvas.itemconfig(self.ui_elements["freq_b"], text=freq_b_display, fill=freq_b_color)
            self.cached_freq_b = freq_b_display
        else:
            # Still update color in case it changed to/from red
            self.canvas.itemconfig(self.ui_elements["freq_b"], fill=freq_b_color)
        
        # Only update mode if changed
        if self.mode_vfo_b != self.cached_mode_b:
            self.canvas.itemconfig(self.ui_elements["mode_b"], text=self.mode_vfo_b)
            self.cached_mode_b = self.mode_vfo_b

        # 3. Update Antenna Display & Split Indicator (only if changed)
        antenna_text = f"ANT {self.antenna}"
        if self.split_enabled:
            antenna_text += " | SPLIT"
        if antenna_text != self.cached_antenna:
            self.canvas.itemconfig(self.ui_elements["antenna_display"], text=antenna_text)
            self.cached_antenna = antenna_text

        # 3b. Animate VFO A Knob (Rotate Dimple based on frequency)
        try:
            khz_part = int(self.frequency.replace(".", "")[-3:])
            angle_rad = math.radians((khz_part / 1000.0) * 360 * 10)
            
            cx, cy = 480, 300
            dx = cx + self.dimple_radius * math.cos(angle_rad)
            dy = cy + self.dimple_radius * math.sin(angle_rad)
            
            self.canvas.coords(self.vfo_a_dimple, dx-8, dy-8, dx+8, dy+8)
        except:
            pass

        # 3b. Animate VFO B Knob
        try:
            khz_part_b = int(self.frequency_vfo_b.replace(".", "")[-3:])
            angle_rad_b = math.radians((khz_part_b / 1000.0) * 360 * 10)
            
            bx, by = 900, 300
            dx_b = bx + self.vfo_b_dimple_radius * math.cos(angle_rad_b)
            dy_b = by + self.vfo_b_dimple_radius * math.sin(angle_rad_b)
            
            self.canvas.coords(self.vfo_b_dimple, dx_b-8, dy_b-8, dx_b+8, dy_b+8)
        except:
            pass

        # 4. Update Meters (only if values change significantly or transmit state changes)
        # S-meter: meter_level is 0-255. Map to 0-25 segments.
        active_segments = int((self.meter_level / 255.0) * 25)
        if active_segments != self.cached_meter_level or self.transmitting != self.cached_transmitting:
            for i, seg in enumerate(self.meter_segments):
                if i < active_segments:
                    self.canvas.itemconfig(seg['id'], fill=seg['on_color'])
                else:
                    self.canvas.itemconfig(seg['id'], fill="#222222") # Off state
            self.cached_meter_level = active_segments
            self.cached_transmitting = self.transmitting
        
        # Power Output Meter — always show polled value (radio returns 0 on RX)
        active_power_segments = int((self.power_meter_level / 255.0) * 25)
        for i, seg in enumerate(self.power_meter_segments):
            if i < active_power_segments:
                self.canvas.itemconfig(seg['id'], fill=seg['on_color'])
            else:
                self.canvas.itemconfig(seg['id'], fill="#222222")

        # SWR Meter — always show polled value (radio returns 0 on RX)
        active_swr_segments = int((self.swr_level / 255.0) * 25)
        for i, seg in enumerate(self.swr_meter_segments):
            if i < active_swr_segments:
                self.canvas.itemconfig(seg['id'], fill=seg['on_color'])
            else:
                self.canvas.itemconfig(seg['id'], fill="#222222")

        # 5. Update Mode LEDs
        modes = ["LSB", "USB", "CW", "AM", "FM"]
        current_mode = self.mode if self.active_vfo == "A" else self.mode_vfo_b
        
        for m in modes:
            led_color = COLOR_LED_GREEN if m == current_mode else COLOR_LED_OFF
            if f"led_{m}" in self.ui_elements:
                self.canvas.itemconfig(self.ui_elements[f"led_{m}"], fill=led_color)

        # 6. Update Control Sliders
        # AF GAIN
        if "af_thumb" in self.ui_elements:
            self.canvas.itemconfig(self.ui_elements["af_value"], text=str(self.af_gain))
            # Update thumb position
            x = self.ui_elements["af_x"]
            y = self.ui_elements["af_y"]
            slider_width = self.ui_elements["af_width"]
            thumb_pos = x - slider_width//2 + (self.af_gain / 100.0) * slider_width
            thumb_width = 7
            slider_height = 14
            self.canvas.coords(
                self.ui_elements["af_thumb"],
                thumb_pos - thumb_width//2, y - slider_height//2 - 2,
                thumb_pos + thumb_width//2, y + slider_height//2 + 2
            )
        
        # SUB AF GAIN
        if "sub_af_thumb" in self.ui_elements:
            self.canvas.itemconfig(self.ui_elements["sub_af_value"], text=str(self.sub_af_gain))
            # Update thumb position
            x = self.ui_elements["sub_af_x"]
            y = self.ui_elements["sub_af_y"]
            slider_width = self.ui_elements["sub_af_width"]
            thumb_pos = x - slider_width//2 + (self.sub_af_gain / 100.0) * slider_width
            thumb_width = 7
            slider_height = 14
            self.canvas.coords(
                self.ui_elements["sub_af_thumb"],
                thumb_pos - thumb_width//2, y - slider_height//2 - 2,
                thumb_pos + thumb_width//2, y + slider_height//2 + 2
            )
        
        # RF GAIN
        if "rf_thumb" in self.ui_elements:
            self.canvas.itemconfig(self.ui_elements["rf_value"], text=str(self.rf_gain))
            # Update thumb position
            x = self.ui_elements["rf_x"]
            y = self.ui_elements["rf_y"]
            slider_width = self.ui_elements["rf_width"]
            thumb_pos = x - slider_width//2 + (self.rf_gain / 100.0) * slider_width
            thumb_width = 7
            slider_height = 14
            self.canvas.coords(
                self.ui_elements["rf_thumb"],
                thumb_pos - thumb_width//2, y - slider_height//2 - 2,
                thumb_pos + thumb_width//2, y + slider_height//2 + 2
            )
        
        # POWER Level
        if "power_thumb" in self.ui_elements:
            self.canvas.itemconfig(self.ui_elements["power_value"], text=str(self.power_level))
            # Update thumb position
            x = self.ui_elements["power_x"]
            y = self.ui_elements["power_y"]
            slider_width = self.ui_elements["power_width"]
            thumb_pos = x - slider_width//2 + (self.power_level / 100.0) * slider_width
            thumb_width = 7
            slider_height = 14
            self.canvas.coords(
                self.ui_elements["power_thumb"],
                thumb_pos - thumb_width//2, y - slider_height//2 - 2,
                thumb_pos + thumb_width//2, y + slider_height//2 + 2
            )

        # 7. Update Interactive Knobs (SHIFT, WIDTH, NOTCH)
        # SHIFT knob
        if "shift_line" in self.ui_elements:
            self.canvas.itemconfig(self.ui_elements["shift_value"], text=str(int(self.shift)))
            # Update indicator line position based on value (0-100 maps to -135° to +135°)
            angle = ((self.shift / 100.0) * 270 - 135) * (math.pi / 180)
            x, y = self.ui_elements["shift_x"], self.ui_elements["shift_y"]
            x2 = x + 23 * math.sin(angle)
            y2 = y - 23 * math.cos(angle)
            self.canvas.coords(self.ui_elements["shift_line"], x, y, x2, y2)
        
        # WIDTH knob
        if "width_line" in self.ui_elements:
            self.canvas.itemconfig(self.ui_elements["width_value"], text=str(int(self.width)))
            angle = ((self.width / 100.0) * 270 - 135) * (math.pi / 180)
            x, y = self.ui_elements["width_x"], self.ui_elements["width_y"]
            x2 = x + 23 * math.sin(angle)
            y2 = y - 23 * math.cos(angle)
            self.canvas.coords(self.ui_elements["width_line"], x, y, x2, y2)
        
        # NOTCH knob
        if "notch_line" in self.ui_elements:
            self.canvas.itemconfig(self.ui_elements["notch_value"], text=str(int(self.notch)))
            angle = ((self.notch / 100.0) * 270 - 135) * (math.pi / 180)
            x, y = self.ui_elements["notch_x"], self.ui_elements["notch_y"]
            x2 = x + 23 * math.sin(angle)
            y2 = y - 23 * math.cos(angle)
            self.canvas.coords(self.ui_elements["notch_line"], x, y, x2, y2)

        # 7. Update Antenna and Tuner LEDs
        if "ant1_led" in self.ui_elements:
            self.canvas.itemconfig(self.ui_elements["ant1_led"], 
                                  fill=COLOR_LED_GREEN if self.antenna == 1 else COLOR_LED_OFF)
        if "ant2_led" in self.ui_elements:
            self.canvas.itemconfig(self.ui_elements["ant2_led"], 
                                  fill=COLOR_LED_GREEN if self.antenna == 2 else COLOR_LED_OFF)
        if "tuner_led" in self.ui_elements:
            self.canvas.itemconfig(self.ui_elements["tuner_led"], 
                                  fill=COLOR_LED_GREEN if self.tuner_active else COLOR_LED_OFF)
        if "vfo_switch_led" in self.ui_elements:
            # Show which VFO is active: green for B, off for A
            self.canvas.itemconfig(self.ui_elements["vfo_switch_led"], 
                                  fill=COLOR_LED_GREEN if self.active_vfo == "B" else COLOR_LED_OFF)
        if "xmit_led" in self.ui_elements:
            # Show transmit status: red when transmitting
            led_color = COLOR_DISPLAY_RED if self.transmitting else COLOR_LED_OFF
            self.canvas.itemconfig(self.ui_elements["xmit_led"], fill=led_color)

        # 8. Update Filter Matrix LEDs
        # APF filters
        for freq in self.apf_filters:
            if f"apf_{freq}_led" in self.ui_elements:
                led_color = COLOR_LED_GREEN if self.apf_filters[freq] else COLOR_LED_OFF
                self.canvas.itemconfig(self.ui_elements[f"apf_{freq}_led"], fill=led_color)
        
        # NR filters
        for freq in self.nr_filters:
            if f"nr_{freq}_led" in self.ui_elements:
                led_color = COLOR_LED_GREEN if self.nr_filters[freq] else COLOR_LED_OFF
                self.canvas.itemconfig(self.ui_elements[f"nr_{freq}_led"], fill=led_color)
        
        # NR OFF button
        if "nr_off_led" in self.ui_elements:
            led_color = COLOR_LED_GREEN if self.nr_off else COLOR_LED_OFF
            self.canvas.itemconfig(self.ui_elements["nr_off_led"], fill=led_color)
        
        # CONTOUR button - update mode text and LED color
        if "contour_mode_txt" in self.ui_elements:
            contour_modes = ["OFF", "L-CUT", "M-CUT", "H-CUT"]
            mode_text = contour_modes[self.contour_mode]
            self.canvas.itemconfig(self.ui_elements["contour_mode_txt"], text=mode_text, fill="#ff9900")
        
        if "contour_led" in self.ui_elements:
            # Different LED colors for different modes
            contour_colors = [COLOR_LED_OFF, "#ffaa00", "#00ff00", "#00aaff"]  # OFF, orange, green, blue
            led_color = contour_colors[self.contour_mode]
            self.canvas.itemconfig(self.ui_elements["contour_led"], fill=led_color)
        
        # 9. Update Connection Status
        if "conn_port_text" in self.ui_elements:
            if MOCK_MODE:
                # Demo mode - orange
                self.canvas.itemconfig(self.ui_elements["conn_port_text"], text="", fill="#ff9900")
                self.canvas.itemconfig(self.ui_elements["conn_led"], fill="#ff9900")
                self.canvas.itemconfig(self.ui_elements["conn_status_text"], text="", fill="#ff9900")
            elif self.serial_port and self.serial_port.is_open:
                # Connected - green - display actual port name
                port_name = self.serial_port.port if hasattr(self.serial_port, 'port') else "CONNECTED"
                self.canvas.itemconfig(self.ui_elements["conn_port_text"], text=port_name, fill="#aaa")
                self.canvas.itemconfig(self.ui_elements["conn_led"], fill="#00ff00")
                if self.cat_read_enabled:
                    status_text = "CONNECTED"
                    status_color = "#00ff00"
                else:
                    status_text = "TX-ONLY"
                    status_color = "#ffaa00"
                self.canvas.itemconfig(self.ui_elements["conn_status_text"], text=status_text, fill=status_color)
            else:
                # Not connected - red
                self.canvas.itemconfig(self.ui_elements["conn_port_text"], text="NOT FOUND", fill="#aaa")
                self.canvas.itemconfig(self.ui_elements["conn_led"], fill="#ff3333")
                self.canvas.itemconfig(self.ui_elements["conn_status_text"], text="DISCONNECTED", fill="#ff3333")
        
        # 10. Draw Help Overlay (if enabled via Ctrl+H)
        if self.show_help:
            # Semi-transparent help overlay
            self.canvas.create_rectangle(0, 0, 1200, 480, fill="#000000", stipple="gray50", tags="help_overlay")
            
            # Help text
            help_lines = [
                "KEYBOARD SHORTCUTS",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "↑ / ↓            : ±10 kHz frequency",
                "Shift + ↑ / ↓    : ±1 kHz frequency",
                "Ctrl + Left      : Toggle VFO A/B",
                "Ctrl + M         : Cycle through modes",
                "Ctrl + '         : Toggle Split Frequency Mode (TX/RX)",
                "Ctrl + H         : Toggle this help",
                "Ctrl + S         : Save settings",
                "Alt + 0-9        : Recall memory channel 0-9",
                "Alt + Shift 0-9  : Store current to memory 0-9",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "Numeric Keypad   : Direct frequency entry",
                "Click VFO Knobs  : Drag to tune | Click to select",
                "Click Buttons    : Mode, antenna, tuner controls",
                f"Memory: {self.selected_memory}  |  Split: {'ON' if self.split_enabled else 'OFF'}",
            ]
            
            help_y = 80
            for i, line in enumerate(help_lines):
                # Highlight title and header
                if i == 0:
                    color = "#ffff00"  # Yellow for title
                    font = ("Arial", 14, "bold")
                elif "━" in line:
                    color = "#888888"
                    font = ("Arial", 10)
                elif "Current Memory" in line:
                    color = "#00ff00"
                    font = ("Arial", 10, "bold")
                else:
                    color = "#cccccc"
                    font = ("Arial", 10)
                
                self.canvas.create_text(
                    600, help_y,
                    text=line, fill=color, font=font, anchor="center",
                    tags="help_overlay"
                )
                help_y += 20
        
        # 11. Display temporary status messages (if active)
        if self.status_message and time.time() < self.status_message_until:
            self.canvas.delete("status_msg")
            # Draw status message banner at bottom center
            self.canvas.create_rectangle(
                400, 440, 800, 470,
                fill="#004400", outline="#00ff00", width=2,
                tags="status_msg"
            )
            self.canvas.create_text(
                600, 455,
                text=self.status_message,
                fill="#00ff00", font=("Arial", 12, "bold"),
                tags="status_msg"
            )
        else:
            # Clear expired messages
            self.canvas.delete("status_msg")
            if time.time() >= self.status_message_until:
                self.status_message = None

    def radio_loop(self):
        """Handles serial communication in background"""
        if not MOCK_MODE:
            try:
                # Use configured SERIAL_PORT/BAUD_RATE when both are set; otherwise auto-detect.
                detected_port, detected_baud, used_autodetect = resolve_serial_settings()
                if used_autodetect:
                    print(f"Attempting auto-detected connection: {detected_port} at {detected_baud} baud")
                else:
                    print(f"Attempting configured connection: {detected_port} at {detected_baud} baud")
                
                # Add retry logic for connection
                max_retries = 3
                retry_count = 0
                
                while retry_count < max_retries:
                    try:
                        self.connect_serial_with_profile(detected_port, detected_baud, timeout_seconds=0.5)
                        print(
                            f"Successfully connected to {detected_port} at {detected_baud} baud"
                            f" using profile {self.serial_profile_name}"
                        )
                        break
                    except Exception as e:
                        retry_count += 1
                        print(f"Connection attempt {retry_count}/{max_retries} failed: {e}")
                        if retry_count < max_retries:
                            time.sleep(1)  # Wait before retrying
                        else:
                            raise e
                
            except Exception as e:
                print(f"Error opening serial port after retries: {e}")
                self.serial_port = None
                return

        while self.running:
            if MOCK_MODE:
                self.simulate_radio()
                time.sleep(0.05) # Faster update for smooth animation
                continue

            try:
                loop_now = time.time()
                local_tx = self.transmitting
                effective_tx = (
                    local_tx
                    or self.radio_tx_active
                    or loop_now < self.tx_meter_hold_until
                )

                # Poll only when CAT readback has been positively validated.
                if (
                    not local_tx
                    and self.cat_read_enabled
                    and self.cat_read_opcode_working is not None
                ):
                    freq_data = self.cat_read_frequency(
                        opcode=self.cat_read_opcode_working,
                        status_param=self.cat_read_status_param_working,
                    )
                    if freq_data:
                        self.parse_freq_data(freq_data)

                # Meter polling
                if CAT_POLL_METER:
                    now = loop_now

                    # Prioritize the transmit meters while keyed so they refresh first.
                    if local_tx:
                        po_val  = self.read_panel_meter(0x80)   # PO meter
                        swr_val = self.read_panel_meter(0x85)   # SWR meter
                        s_val   = None  # Do not poll S-meter during TX
                        self.meter_level = 0  # Force RX S-meter dark during TX
                    else:
                        s_val   = self.read_panel_meter(0x00)   # S-meter
                        po_val  = self.read_panel_meter(0x80)   # PO meter
                        swr_val = self.read_panel_meter(0x85)   # SWR meter

                    if s_val is not None:
                        self.meter_level = s_val

                    if local_tx:
                        # During TX, latch the most recent valid readings and do not decay.
                        got_tx_meter = False
                        if po_val is not None:
                            self.power_meter_level = po_val
                            got_tx_meter = True
                        if swr_val is not None:
                            self.swr_level = swr_val
                            got_tx_meter = True

                        if got_tx_meter:
                            self.last_tx_meter_update = now
                            self.tx_meter_hold_until = max(self.tx_meter_hold_until, now + 0.25)
                    else:
                        # RX mode — accept PO/SWR only if they diverge clearly from the
                        # concurrent S-meter reading (indicates front-panel TX in progress).
                        s_ref = s_val if s_val is not None else int(self.meter_level)
                        if po_val is not None and abs(po_val - s_ref) > 20:
                            self.power_meter_level = po_val
                            self.last_tx_meter_update = now
                        else:
                            self.power_meter_level = max(0, self.power_meter_level - 2)
                        if swr_val is not None and abs(swr_val - s_ref) > 20:
                            self.swr_level = swr_val
                            self.last_tx_meter_update = now
                        else:
                            self.swr_level = max(0, self.swr_level - 2)

                time.sleep(CAT_POLL_INTERVAL_S)

            except Exception as e:
                print(f"Serial Error: {e}")
                self.connection_stable = False
                # Try to reconnect with exponential backoff
                current_time = time.time()
                if current_time - self.last_reconnect_attempt > SERIAL_RETRY_INTERVAL:
                    self.last_reconnect_attempt = current_time
                    try:
                        if self.serial_port:
                            try:
                                self.serial_port.close()
                            except:
                                pass
                        # Attempt new connection. Keep using fixed config if explicitly set.
                        detected_port, detected_baud, _ = resolve_serial_settings()
                        self.connect_serial_with_profile(detected_port, detected_baud, timeout_seconds=SERIAL_TIMEOUT)
                        self.connection_stable = True
                        print(
                            f"Reconnected to {detected_port} at {detected_baud} baud"
                            f" using profile {self.serial_profile_name}"
                        )
                    except Exception as reconnect_error:
                        print(f"Reconnection failed: {reconnect_error}")
                        self.serial_port = None
                time.sleep(1)

    def parse_freq_data(self, data):
        """Parse frequency data from radio"""
        try:
            if self.cat_read_opcode_working == 0x10 and self.cat_read_status_param_working == 0x03:
                decoded_1, decoded_2 = decode_status_vfo_pair_10hz(data)
                vfo_a_10hz, vfo_b_10hz = choose_stable_vfo_assignment(
                    decoded_1,
                    decoded_2,
                    self.frequency,
                    self.frequency_vfo_b,
                )
                if vfo_a_10hz is None:
                    return

                selected_freq = frequency_10hz_to_display(vfo_a_10hz)
                if vfo_b_10hz is not None:
                    self.frequency_vfo_b = frequency_10hz_to_display(vfo_b_10hz)

                if CAT_SYNC_MODE_FROM_STATUS and time.time() >= self.mode_sync_block_until and len(data) >= 24:
                    rec_a = data[0:16]
                    rec_b = data[16:32]
                    # Keep mode aligned with whichever mapping we chose above.
                    if vfo_a_10hz == decoded_2 and vfo_b_10hz == decoded_1:
                        rec_a, rec_b = rec_b, rec_a

                    mode_a = decode_status_mode(rec_a[7])
                    if mode_a:
                        self.mode = mode_a

                    mode_b = decode_status_mode(rec_b[7])
                    if mode_b:
                        self.mode_vfo_b = mode_b

                if CAT_SYNC_ANTENNA_FROM_STATUS and len(data) >= 24:
                    rec_a = data[0:16]
                    rec_b = data[16:32]
                    if vfo_a_10hz == decoded_2 and vfo_b_10hz == decoded_1:
                        rec_a, rec_b = rec_b, rec_a

                    # Prefer active VFO record for antenna flags.
                    ant_source = rec_a if self.active_vfo == "A" else rec_b
                    ant = decode_status_antenna(ant_source[9])
                    if ant in (1, 2):
                        self.antenna = ant

                if len(data) >= 24:
                    rec_a = data[0:16]
                    rec_b = data[16:32]
                    if vfo_a_10hz == decoded_2 and vfo_b_10hz == decoded_1:
                        rec_a, rec_b = rec_b, rec_a

                    tx_source = rec_a if self.active_vfo == "A" else rec_b
                    self.radio_tx_active = decode_status_transmitting(tx_source[0])
                    if self.radio_tx_active:
                        self.tx_meter_hold_until = time.time() + 0.40

                # Require two consecutive matching reads before updating UI.
                if selected_freq == self.last_polled_freq:
                    self.last_polled_freq_hits += 1
                else:
                    self.last_polled_freq = selected_freq
                    self.last_polled_freq_hits = 1

                if self.last_polled_freq_hits >= 2:
                    self.frequency = selected_freq
                return

            selected_freq = select_frequency_from_stream(data, self.frequency)
            if not selected_freq:
                return

            # Require two consecutive matching reads before updating UI.
            if selected_freq == self.last_polled_freq:
                self.last_polled_freq_hits += 1
            else:
                self.last_polled_freq = selected_freq
                self.last_polled_freq_hits = 1

            if self.last_polled_freq_hits >= 2:
                self.frequency = selected_freq
        except Exception as e:
            print(f"Error parsing frequency data: {e}")
            import traceback
            traceback.print_exc()

    def simulate_radio(self):
        """Enhanced simulation for smooth animation"""
        import random
        t = time.time()
        
        if self.transmitting:
            # Simulate output power based on power level setting
            target_power = int((self.power_level / 100.0) * 250)  # Scale to 0-250
            # Add slight variation
            target_power += random.randint(-5, 5)
            target_power = max(0, min(255, target_power))
            self.power_meter_level += (target_power - self.power_meter_level) * 0.3
            
            # Simulate SWR (usually good, occasionally spikes)
            if random.random() > 0.95:
                target_swr = random.randint(80, 150)  # Occasional high SWR
            else:
                target_swr = random.randint(20, 50)  # Normal low SWR (1.5:1 range)
            self.swr_level += (target_swr - self.swr_level) * 0.3
            
            # S-meter can still show signals while transmitting
            base_signal = int(abs(math.sin(t * 5)) * 200)
            target_meter = int(base_signal * (self.rf_gain / 100.0))
        else:
            # Not transmitting - power and SWR meters go to zero
            self.power_meter_level *= 0.7  # Smooth decay
            self.swr_level *= 0.7
            
            # Simulate received signal - affected by RF gain
            # Base signal varies with time (simulating fading)
            base_signal = int(abs(math.sin(t * 5)) * 200)
            # Apply RF gain attenuation: rf_gain of 0 = no signal, 100 = full signal
            target_meter = int(base_signal * (self.rf_gain / 100.0))
            
        # Smooth meter movement
        self.meter_level += (target_meter - self.meter_level) * 0.2

    def set_mode_for_frequency(self, vfo):
        """Set appropriate mode based on frequency (LSB below 10 MHz, USB above)"""
        try:
            if vfo == "A":
                freq_str = self.frequency.replace(".", "")
                # Parse as integer in 10Hz units, convert to MHz
                freq_mhz = int(freq_str) / 100000.0
                # Below 10 MHz use LSB, above use USB
                if freq_mhz < 10.0:
                    self.mode = "LSB"
                else:
                    self.mode = "USB"
            else:
                freq_str = self.frequency_vfo_b.replace(".", "")
                freq_mhz = int(freq_str) / 100000.0
                if freq_mhz < 10.0:
                    self.mode_vfo_b = "LSB"
                else:
                    self.mode_vfo_b = "USB"
        except Exception as e:
            print(f"Mode setting error: {e}")


# Main execution
if __name__ == "__main__":
    app = HamSimulatorApp()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        # Graceful shutdown when launched from terminal and interrupted with Ctrl+C.
        print("\nKeyboard interrupt received, shutting down...")
        try:
            app.on_close()
        except Exception:
            pass