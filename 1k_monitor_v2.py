import customtkinter as ctk
import serial
import threading
import time
import math
import random

# --- CONFIGURATION ---
# SERIAL_PORT = 'COM3'  # Windows example
SERIAL_PORT = '/dev/tty.usbserial-AB01'  # Mac example
BAUD_RATE = 4800
MOCK_MODE = True  # Set to False to use real radio

# --- COLORS (FT-1000MP Palette) ---
COLOR_CHASSIS = "#2b2b2b"
COLOR_BEZEL = "#1a1a1a"
COLOR_DISPLAY_BG = "#000000"
COLOR_DISPLAY_OFF = "#221100"  # Dim amber
COLOR_DISPLAY_ON = "#ff9900"   # Bright amber (Yaesu style)
COLOR_DISPLAY_RED = "#ff3333"  # TX color
COLOR_KNOB_MAIN = "#151515"
COLOR_KNOB_RING = "#333333"
COLOR_TEXT_LABEL = "#aaaaaa"
COLOR_LED_GREEN = "#00ff00"
COLOR_LED_OFF = "#113311"

class HamSimulatorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window Setup
        self.title("WT1W Ham Monitor - Virtual FT-1000MP")
        self.geometry("1200x480")
        ctk.set_appearance_mode("Dark")
        self.resizable(False, False)

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
        self.rf_gain = 80  # 0-100
        self.antenna = 1   # 1 or 2
        self.tuner_active = False
        self.freq_entry_buffer = ""  # For direct frequency entry
        self.freq_entry_mode = False
        
        # Dynamic Elements (Store IDs for updating)
        self.ui_elements = {}

        # Canvas Setup (The Radio Face)
        self.canvas = ctk.CTkCanvas(self, width=1200, height=480, bg=COLOR_CHASSIS, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Drawing Layers
        self.draw_chassis()
        self.draw_display_window()
        self.draw_knobs()
        self.draw_buttons()
        
        self.init_dynamic_display()

        # Start Radio Thread
        self.thread = threading.Thread(target=self.radio_loop, daemon=True)
        self.thread.start()

        # Start Animation Loop
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
        
        # === Small Knobs (Shift/Width/AF/RF) ===
        # AF GAIN Knob (Interactive)
        self.draw_control_knob(100, 350, "AF GAIN", "af")
        # RF GAIN Knob (Interactive)
        self.draw_control_knob(200, 350, "RF GAIN", "rf")
        # Static knobs
        knob_positions = [(1100, 250, "SHIFT"), (1100, 350, "WIDTH")]
        for x, y, label in knob_positions:
            self.canvas.create_oval(x-20, y-20, x+20, y+20, fill="#222", outline="#555")
            self.canvas.create_line(x, y-20, x, y-10, fill="white", width=2) # Marker
            self.canvas.create_text(x, y-35, text=label, fill=COLOR_TEXT_LABEL, font=("Arial", 8))

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
                
                btn = self.canvas.create_rectangle(x, y, x+40, y+25, fill="#333", outline="#555", width=2)
                self.canvas.create_text(x+20, y+12, text=label, fill="#aaa", font=("Arial", 10, "bold"))
                
                # Bind click event
                self.canvas.tag_bind(btn, "<Button-1>", lambda e, key=label: self.keypad_press(key))

        # Mode Buttons (Left of VFO)
        modes = ["LSB", "USB", "CW", "AM", "FM"]
        mx, my = 320, 220
        for mode in modes:
            # Button
            btn = self.canvas.create_rectangle(mx, my, mx+50, my+25, fill="#333", outline="black")
            # Label
            self.canvas.create_text(mx+25, my+12, text=mode, fill="#aaa", font=("Arial", 9))
            # LED Indicator (Dynamic)
            led = self.canvas.create_rectangle(mx-10, my+8, mx-4, my+18, fill=COLOR_LED_OFF, outline="")
            self.ui_elements[f"led_{mode}"] = led
            # Bind click event
            self.canvas.tag_bind(btn, "<Button-1>", lambda e, m=mode: self.mode_button_click(m))
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

    def draw_control_knob(self, x, y, label, knob_id):
        """Draw an interactive knob control"""
        # Knob body
        knob = self.canvas.create_oval(x-20, y-20, x+20, y+20, fill="#222", outline="#555", width=2)
        # Position indicator line
        line = self.canvas.create_line(x, y-20, x, y-10, fill="white", width=2)
        # Label
        self.canvas.create_text(x, y-35, text=label, fill=COLOR_TEXT_LABEL, font=("Arial", 8))
        # Value display
        value_text = self.canvas.create_text(x, y+35, text="50", fill=COLOR_DISPLAY_ON, font=("Arial", 10, "bold"))
        
        # Store elements
        self.ui_elements[f"{knob_id}_knob"] = knob
        self.ui_elements[f"{knob_id}_line"] = line
        self.ui_elements[f"{knob_id}_value"] = value_text
        
        # Bind mouse events
        self.canvas.tag_bind(knob, "<Button-1>", lambda e, kid=knob_id: self.knob_click(e, kid))
        self.canvas.tag_bind(knob, "<B1-Motion>", lambda e, kid=knob_id: self.knob_drag(e, kid, x, y))

    def draw_control_button(self, x, y, label, button_id):
        """Draw an interactive button control"""
        # Button rectangle
        btn = self.canvas.create_rectangle(x, y, x+60, y+30, fill="#333", outline="#666", width=2)
        # Button label
        self.canvas.create_text(x+30, y+15, text=label, fill="#aaa", font=("Arial", 10, "bold"))
        # LED indicator
        led = self.canvas.create_oval(x+5, y+5, x+12, y+12, fill=COLOR_LED_OFF, outline="")
        
        # Store elements
        self.ui_elements[f"{button_id}_btn"] = btn
        self.ui_elements[f"{button_id}_led"] = led
        
        # Bind click event
        self.canvas.tag_bind(btn, "<Button-1>", lambda e, bid=button_id: self.button_click(bid))

    def knob_click(self, event, knob_id):
        """Handle knob click"""
        pass  # Store initial click position if needed

    def knob_drag(self, event, knob_id, center_x, center_y):
        """Handle knob dragging to adjust value"""
        # Calculate angle from center
        dx = event.x - center_x
        dy = event.y - center_y
        angle = math.atan2(dy, dx)
        
        # Convert to 0-100 value (using angle)
        # Map -π to π to 0-100
        value = int(((angle + math.pi) / (2 * math.pi)) * 100)
        
        if knob_id == "af":
            self.af_gain = value
        elif knob_id == "rf":
            self.rf_gain = value

    def button_click(self, button_id):
        """Handle button clicks"""
        if button_id == "ant1":
            self.antenna = 1
        elif button_id == "ant2":
            self.antenna = 2
        elif button_id == "tuner":
            self.tuner_active = not self.tuner_active
        elif button_id == "vfo_switch":
            # Toggle between VFO A and B
            self.active_vfo = "B" if self.active_vfo == "A" else "A"

    def mode_button_click(self, mode):
        """Handle mode button clicks"""
        # Set mode for the active VFO
        if self.active_vfo == "A":
            self.mode = mode
        else:
            self.mode_vfo_b = mode

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
            
            # Format as XX.XXX.XX (e.g., 14320000 -> 14.320.00)
            formatted = f"{entry[0:2]}.{entry[2:5]}.{entry[5:7]}"
            
            # Remove leading zero if present
            if formatted.startswith("0"):
                formatted = formatted[1:]
            
            # Validate frequency range (1.8-30 MHz)
            freq_mhz = float(entry[0:2] + "." + entry[2:])
            if 1.8 <= freq_mhz <= 30.0:
                if self.active_vfo == "A":
                    self.frequency = formatted
                else:
                    self.frequency_vfo_b = formatted
        except Exception as e:
            print(f"Frequency entry error: {e}")

    def vfo_click(self, vfo):
        """Handle VFO knob click - set as active VFO"""
        self.active_vfo = vfo

    def vfo_drag(self, event, vfo, center_x, center_y):
        """Handle VFO knob dragging to tune frequency"""
        # Calculate angle from center
        dx = event.x - center_x
        dy = event.y - center_y
        angle = math.atan2(dy, dx)
        
        # Convert angle to frequency adjustment (-180 to 180 degrees = -5kHz to +5kHz)
        freq_offset = (angle / math.pi) * 5  # kHz
        
        # Get current frequency and adjust
        if vfo == "A":
            self.adjust_frequency("A", freq_offset)
        else:
            self.adjust_frequency("B", freq_offset)

    def adjust_frequency(self, vfo, delta_khz):
        """Adjust frequency by delta in kHz"""
        try:
            if vfo == "A":
                freq_str = self.frequency.replace(".", "")
                freq_khz = float(freq_str) / 100.0  # Convert to kHz
                freq_khz += delta_khz
                # Limit to ham bands (1.8 - 30 MHz)
                freq_khz = max(1800, min(30000, freq_khz))
                # Format back
                freq_str = f"{int(freq_khz * 100):08d}"
                self.frequency = f"{freq_str[0:2]}.{freq_str[2:5]}.{freq_str[5:7]}"
                if self.frequency.startswith("0"):
                    self.frequency = self.frequency[1:]
            else:
                freq_str = self.frequency_vfo_b.replace(".", "")
                freq_khz = float(freq_str) / 100.0
                freq_khz += delta_khz
                freq_khz = max(1800, min(30000, freq_khz))
                freq_str = f"{int(freq_khz * 100):08d}"
                self.frequency_vfo_b = f"{freq_str[0:2]}.{freq_str[2:5]}.{freq_str[5:7]}"
                if self.frequency_vfo_b.startswith("0"):
                    self.frequency_vfo_b = self.frequency_vfo_b[1:]
        except Exception as e:
            print(f"Frequency adjustment error: {e}")

    def init_dynamic_display(self):
        """Creates the text and meter bars that change"""
        
        # === VFO A Display ===
        # Background "88.888.88" ghost segments for realism
        self.canvas.create_text(400, 75, text="88.888.88", fill=COLOR_DISPLAY_OFF, font=("Courier", 50, "bold"))
        # Active Text
        self.ui_elements["freq_a"] = self.canvas.create_text(400, 75, text=self.frequency, fill=COLOR_DISPLAY_ON, font=("Courier", 50, "bold"))
        self.ui_elements["mode_a"] = self.canvas.create_text(320, 40, text=self.mode, fill="#00ff00", font=("Arial", 12, "bold"))
        self.canvas.create_text(400, 35, text="VFO A", fill="#cc5500", font=("Arial", 10, "bold"))

        # === VFO B Display ===
        self.canvas.create_text(800, 75, text="88.888.88", fill=COLOR_DISPLAY_OFF, font=("Courier", 50, "bold"))
        self.ui_elements["freq_b"] = self.canvas.create_text(800, 75, text=self.frequency_vfo_b, fill=COLOR_DISPLAY_ON, font=("Courier", 50, "bold"))
        self.ui_elements["mode_b"] = self.canvas.create_text(880, 40, text=self.mode_vfo_b, fill="#00ff00", font=("Arial", 12, "bold"))
        self.canvas.create_text(800, 35, text="VFO B", fill="#cc5500", font=("Arial", 10, "bold"))

        # === Meters (S-Meter / PO) ===
        # We create 30 individual rectangle segments
        self.meter_segments = []
        meter_x_start = 80
        meter_y = 60
        for i in range(30):
            color = "#00ff00" # Green
            if i > 20: color = "#ffff00" # Yellow
            if i > 25: color = "#ff0000" # Red
            
            # Create the segment (initially hidden/dim)
            seg = self.canvas.create_rectangle(
                meter_x_start + (i*6), meter_y, 
                meter_x_start + (i*6) + 4, meter_y + 10, 
                fill="#222", outline=""
            )
            self.meter_segments.append({'id': seg, 'on_color': color})
            
            # Ruler markings underneath
            if i % 5 == 0:
                self.canvas.create_line(meter_x_start + (i*6), meter_y+15, meter_x_start + (i*6), meter_y+20, fill="#666")

    def animate(self):
        """Main UI Update Loop"""
        try:
            self.update_face()
        except Exception as e:
            print(f"UI Error: {e}")
        
        self.after(50, self.animate)

    def update_face(self):
        # 1. Update Frequency A
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
        
        self.canvas.itemconfig(self.ui_elements["freq_a"], text=freq_a_display, fill=freq_a_color)
        self.canvas.itemconfig(self.ui_elements["mode_a"], text=self.mode)

        # 2. Update Frequency B
        freq_b_color = COLOR_DISPLAY_RED if (self.transmitting and self.active_vfo == "B") else COLOR_DISPLAY_ON
        if self.active_vfo != "B": freq_b_color = "#885500"
        
        # Show entry buffer if in entry mode and VFO B is active
        freq_b_display = self.frequency_vfo_b
        if self.freq_entry_mode and self.active_vfo == "B":
            entry_padded = self.freq_entry_buffer.ljust(8, '_')
            freq_b_display = f"{entry_padded[0:2]}.{entry_padded[2:5]}.{entry_padded[5:7]}"
            if freq_b_display.startswith("_"):
                freq_b_display = " " + freq_b_display[1:]
        
        self.canvas.itemconfig(self.ui_elements["freq_b"], text=freq_b_display, fill=freq_b_color)
        self.canvas.itemconfig(self.ui_elements["mode_b"], text=self.mode_vfo_b)

        # 3. Animate VFO A Knob (Rotate Dimple based on frequency)
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

        # 4. Update Meter
        # meter_level is 0-255. Map to 0-30 segments.
        active_segments = int((self.meter_level / 255.0) * 30)
        for i, seg in enumerate(self.meter_segments):
            if i < active_segments:
                self.canvas.itemconfig(seg['id'], fill=seg['on_color'])
            else:
                self.canvas.itemconfig(seg['id'], fill="#222222") # Off state

        # 5. Update Mode LEDs
        modes = ["LSB", "USB", "CW", "AM", "FM"]
        current_mode = self.mode if self.active_vfo == "A" else self.mode_vfo_b
        
        for m in modes:
            led_color = COLOR_LED_GREEN if m == current_mode else COLOR_LED_OFF
            if f"led_{m}" in self.ui_elements:
                self.canvas.itemconfig(self.ui_elements[f"led_{m}"], fill=led_color)

        # 6. Update Control Knobs
        # AF GAIN
        if "af_value" in self.ui_elements:
            self.canvas.itemconfig(self.ui_elements["af_value"], text=str(self.af_gain))
            angle = (self.af_gain / 100.0) * 2 * math.pi - math.pi
            x, y = 100, 350
            x2 = x + 18 * math.cos(angle - math.pi/2)
            y2 = y + 18 * math.sin(angle - math.pi/2)
            self.canvas.coords(self.ui_elements["af_line"], x, y, x2, y2)
        
        # RF GAIN
        if "rf_value" in self.ui_elements:
            self.canvas.itemconfig(self.ui_elements["rf_value"], text=str(self.rf_gain))
            angle = (self.rf_gain / 100.0) * 2 * math.pi - math.pi
            x, y = 200, 350
            x2 = x + 18 * math.cos(angle - math.pi/2)
            y2 = y + 18 * math.sin(angle - math.pi/2)
            self.canvas.coords(self.ui_elements["rf_line"], x, y, x2, y2)

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

    def radio_loop(self):
        """Handles serial communication in background"""
        if not MOCK_MODE:
            try:
                ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.5)
            except Exception as e:
                print(f"Error opening serial port: {e}")
                return

        while self.running:
            if MOCK_MODE:
                self.simulate_radio()
                time.sleep(0.05) # Faster update for smooth animation
                continue

            try:
                # Real Radio Logic (Same as before)
                # 1. Read Frequency
                cmd_freq = bytearray([0x00, 0x00, 0x00, 0x00, 0x03])
                ser.write(cmd_freq)
                data = ser.read(5)
                if len(data) == 5:
                    self.parse_freq_data(data)

                # 2. Read Meter
                cmd_meter = bytearray([0x00, 0x00, 0x00, 0x00, 0x10])
                ser.write(cmd_meter)
                meter_byte = ser.read(1)
                if len(meter_byte) == 1:
                    self.meter_level = ord(meter_byte)

            except Exception as e:
                print(f"Serial Error: {e}")
                time.sleep(1)

    def parse_freq_data(self, data):
        # ... (Same parsing logic as original) ...
        freq_str = f"{data[0]:02x}{data[1]:02x}{data[2]:02x}{data[3]:02x}"
        formatted_freq = f"{freq_str[0:2]}.{freq_str[2:5]}.{freq_str[5:7]}"
        if formatted_freq.startswith("0"):
            formatted_freq = formatted_freq[1:]
        self.frequency = formatted_freq
        
        mode_byte = data[4]
        mode_map = {0x00: "LSB", 0x01: "USB", 0x02: "CW", 0x03: "AM", 0x04: "FM"}
        self.mode = mode_map.get(mode_byte & 0x07, "DATA")

    def simulate_radio(self):
        """Enhanced simulation for smooth animation"""
        # Wiggle frequency VFO A (simulating tuning)
        import random
        base_khz = 320
        # Create a smooth sine wave drift for testing knob rotation
        t = time.time()
        offset = int(math.sin(t * 2) * 50) + 50
        
        self.frequency = f"14.{base_khz}.{offset:02d}"
        
        # Random TX
        if random.random() > 0.98:
            self.transmitting = not self.transmitting
            
        if self.transmitting:
            target_meter = random.randint(180, 250)
        else:
            target_meter = int(abs(math.sin(t * 5)) * 150) # Bouncing S-meter
            
        # Smooth meter movement
        self.meter_level += (target_meter - self.meter_level) * 0.2

if __name__ == "__main__":
    app = HamSimulatorApp()
    app.mainloop()