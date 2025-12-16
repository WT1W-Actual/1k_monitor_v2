# WT1W Ham Monitor - Virtual FT-1000MP

A virtual ham radio interface simulating the Yaesu FT-1000MP Mark-V transceiver. Features a realistic display with functional controls for monitoring and controlling ham radio operations.

![Ham Radio Monitor](screenshot.png)

## Features

### Functional Controls
- **Dual VFO (A/B)** - Independent frequency control for two VFOs
- **VFO Knobs** - Click and drag to tune frequencies (1.8-30 MHz)
- **Numeric Keypad** - Direct frequency entry
  - Enter frequency digits (e.g., 1432 for 14.320 MHz)
  - CLR to clear entry
  - ENT to set frequency
- **Mode Selection** - LSB, USB, CW, AM, FM
- **A/B Switch** - Toggle between VFO A and VFO B
- **AF/RF Gain Controls** - Adjustable audio and RF gain (0-100)
- **Antenna Selection** - Switch between ANT 1 and ANT 2
- **Tuner Control** - Toggle antenna tuner on/off
- **EDSP Filter Matrix** - Enhanced DSP filtering controls
  - **APF** - 5 audio peak filters (mutually exclusive)
  - **NR** - 5 noise reduction levels plus OFF (mutually exclusive)
  - **CONTOUR** - Cycling audio shaping (OFF → Low-Cut → Mid-Cut → High-Cut)

### Display Elements
- **Dual Frequency Displays** - Large amber displays for both VFOs
- **S-Meter / Power Meter** - 30-segment bar graph with color gradient
- **Mode Indicators** - Green LED indicators for active mode
- **VFO Indicators** - Visual feedback showing active VFO
- **Rotating Knob Indicators** - Animated dimples on VFO knobs
- **Connection Status** - Bottom status bar with LED indicator
  - **Orange LED** - Simulation mode
  - **Green LED** - Connected to radio
  - **Red LED** - Disconnected

### Modes
- **Mock Mode** (default) - Simulated radio with animated display
- **Real Radio Mode** - Connect to actual FT-1000MP via serial port

## Installation

### Requirements
- Python 3.7+
- CustomTkinter
- PySerial

### Setup

1. Clone the repository:
```bash
git clone https://github.com/YOUR_USERNAME/1k_monitor_v2.git
cd 1k_monitor_v2
```

2. Create a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On macOS/Linux
# or
.venv\Scripts\activate  # On Windows
```

3. Install dependencies:
```bash
pip install customtkinter pyserial
```

## Usage

### Mock Mode (No Radio Required)
```bash
python 1k_monitor_v2.py
```

The application starts in mock mode by default, simulating a working radio with animated displays.

### Real Radio Mode
1. Connect your FT-1000MP to your computer via serial cable (USB-to-serial adapter recommended)
2. Set `MOCK_MODE = False` in `1k_monitor_v2.py`
3. Run the application - it will **automatically detect**:
   - Available USB serial ports
   - Correct serial port with connected radio
   - Proper baud rate (tests 4800, 9600, 19200, 38400, 57600)
4. Check console output to see detected port and baud rate

**Manual Configuration** (if auto-detect fails):
Edit the configuration in `1k_monitor_v2.py`:
```python
SERIAL_PORT = '/dev/tty.usbserial-AB01'  # Mac
# or
SERIAL_PORT = 'COM3'  # Windows
BAUD_RATE = 4800
MOCK_MODE = False  # Set to False for real radio
```

## Controls

### VFO Tuning
- **Click VFO knob** - Select as active VFO
- **Drag VFO knob** - Tune frequency
- **A/B button** - Toggle between VFOs

### Frequency Entry
1. Select VFO (A or B)
2. Enter digits on keypad (4-8 digits)
3. Press ENT to set frequency
4. Press CLR to cancel

### Mode Selection
Click any mode button (LSB, USB, CW, AM, FM) to change the mode of the active VFO.

### Gain Controls
Click and drag the AF GAIN or RF GAIN knobs to adjust levels (0-100).

### EDSP Filters
- **APF buttons** - Select one of 5 audio peak filters (mutually exclusive)
- **NR buttons** - Select noise reduction level 1-5 or OFF (mutually exclusive)
- **CONTOUR button** - Click to cycle through audio contour modes:
  - OFF (LED off)
  - Low-Cut / High-Pass (orange LED)
  - Mid-Cut / Notch (green LED)
  - High-Cut / Low-Pass (blue LED)

## Configuration

Key settings at the top of `1k_monitor_v2.py`:

```python
SERIAL_PORT = '/dev/tty.usbserial-AB01'  # Default port (auto-detected in real mode)
BAUD_RATE = 4800                          # Default baud rate (auto-detected in real mode)
MOCK_MODE = True                          # True for simulation, False for real radio
```

### Auto-Detection Features
When `MOCK_MODE = False`, the application automatically:
- Scans for USB serial adapters
- Probes each port with FT-1000MP CAT commands
- Tests common baud rates (4800, 9600, 19200, 38400, 57600)
- Connects to the first responding radio
- Displays detected port and baud rate in console

## Color Scheme

The interface uses authentic Yaesu FT-1000MP colors:
- **Amber display** - Classic radio display aesthetic
- **Green LEDs** - Active indicators
- **Dark chassis** - Professional appearance

## License

MIT License - feel free to use and modify for your ham radio projects.

## Author

WT1W

## Acknowledgments

Inspired by the legendary Yaesu FT-1000MP Mark-V transceiver.

73! 🎙️📻
