#!/usr/bin/env python3
"""
Interactive CAT command tester for FT-1000MP.
Manually send commands and inspect responses.
"""

import serial
import time
import struct

PORT = 'COM3'
BAUD = 4800
TIMEOUT = 0.5

def hex_bytes(data):
    return " ".join(f"{b:02X}" for b in data)

def send_command(ser, cmd_bytes, expected_response_len, description=""):
    """Send a CAT command and read the response."""
    print(f"\n{'='*80}")
    print(f"Sending: {description or 'CAT Command'}")
    print(f"  TX: {hex_bytes(cmd_bytes)}")
    
    # Send command
    ser.reset_input_buffer()
    ser.write(cmd_bytes)
    time.sleep(0.2)  # Wait for response
    
    # Read response
    response = ser.read(expected_response_len) if expected_response_len > 0 else b""
    
    if response:
        print(f"  RX ({len(response)} bytes): {hex_bytes(response)}")
        
        # Try to interpret as BCD frequency if 4 or 5 bytes
        if len(response) >= 4:
            print(f"  Analysis:")
            # Try first 4 bytes as frequency
            for start in range(len(response) - 3):
                test_bytes = response[start:start+4]
                valid_bcd = all(((b >> 4) & 0x0F) <= 9 and (b & 0x0F) <= 9 for b in test_bytes)
                bcd_str = "".join(f"{b:02x}" for b in test_bytes)
                if valid_bcd:
                    freq_10hz = int(bcd_str)
                    freq_mhz = freq_10hz / 100000.0
                    print(f"    Bytes[{start}:{start+4}] = {hex_bytes(test_bytes)} → Valid BCD → {freq_mhz:.5f} MHz")
                else:
                    invalid_nibbles = []
                    for i, b in enumerate(test_bytes):
                        high = (b >> 4) & 0x0F
                        low = b & 0x0F
                        if high > 9:
                            invalid_nibbles.append(f"b[{i}]_hi={high}")
                        if low > 9:
                            invalid_nibbles.append(f"b[{i}]_lo={low}")
                    if invalid_nibbles:
                        print(f"    Bytes[{start}:{start+4}] = {hex_bytes(test_bytes)} → Invalid BCD ({', '.join(invalid_nibbles)})")
    else:
        print(f"  RX: (NO RESPONSE)")
    
    return response

def main():
    try:
        ser = serial.Serial(PORT, BAUD, timeout=TIMEOUT)
        print(f"Connected to {PORT} at {BAUD} baud (timeout={TIMEOUT}s)")
        print("Expected radio frequency: 18.170.22 MHz")
        print("Expected BCD bytes (MSB-first): 01 81 70 22")
        
        while True:
            print(f"\n{'-'*80}")
            print("Choose a command to test:")
            print("  1) Read frequency (opcode 0x03)")
            print("  2) Read frequency (opcode 0x00)")
            print("  3) Status Update Current Data (opcode 0x10, param 0x02)")
            print("  4) Read Meter (opcode 0x10)")
            print("  5) Read S-Meter (opcode 0xF7)")
            print("  6) Read Power Meter (opcode 0xFA)")
            print("  q) Quit")
            choice = input("\nSelect: ").strip().lower()
            
            if choice == '1':
                cmd = bytearray([0x00, 0x00, 0x00, 0x00, 0x03])
                send_command(ser, cmd, 5, "Read Frequency (opcode 0x03)")
            
            elif choice == '2':
                cmd = bytearray([0x00, 0x00, 0x00, 0x00, 0x00])
                send_command(ser, cmd, 5, "Read Frequency (opcode 0x00)")
            
            elif choice == '3':
                cmd = bytearray([0x00, 0x00, 0x00, 0x02, 0x10])
                send_command(ser, cmd, 16, "Status Update - Current Operating Data (opcode 0x10, param 0x02)")
            
            elif choice == '4':
                cmd = bytearray([0x00, 0x00, 0x00, 0x00, 0x10])
                send_command(ser, cmd, 1, "Read Meter (opcode 0x10, param 0x00)")
            
            elif choice == '5':
                cmd = bytearray([0x00, 0x00, 0x00, 0x00, 0xF7])
                send_command(ser, cmd, 2, "S-Meter Level (opcode 0xF7)")
            
            elif choice == '6':
                cmd = bytearray([0x00, 0x00, 0x00, 0x00, 0xFA])
                send_command(ser, cmd, 2, "Power Meter Level (opcode 0xFA)")
            
            elif choice == 'q':
                break
            else:
                print("Invalid choice")
        
        ser.close()
        print("Connection closed.")
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
