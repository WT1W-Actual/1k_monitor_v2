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

### Display Elements
- **Dual Frequency Displays** - Large amber displays for both VFOs
- **S-Meter / Power Meter** - 30-segment bar graph with color gradient
- **Mode Indicators** - Green LED indicators for active mode
- **VFO Indicators** - Visual feedback showing active VFO
- **Rotating Knob Indicators** - Animated dimples on VFO knobs

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
1. Connect your FT-1000MP to your computer via serial cable
2. Edit the configuration in `1k_monitor_v2.py`:
```python
SERIAL_PORT = '/dev/tty.usbserial-AB01'  # Mac
# or
SERIAL_PORT = 'COM3'  # Windows
BAUD_RATE = 4800
MOCK_MODE = False  # Set to False for real radio
```
3. Run the application

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

## Configuration

Key settings at the top of `1k_monitor_v2.py`:

```python
SERIAL_PORT = '/dev/tty.usbserial-AB01'  # Serial port for radio
BAUD_RATE = 4800                          # Radio baud rate
MOCK_MODE = True                          # True for simulation, False for real radio
```

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
