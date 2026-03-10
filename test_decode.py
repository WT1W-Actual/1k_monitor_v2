#!/usr/bin/env python3
"""
Debug script to decode the Status Update response from the radio.
Radio is currently at 18.170.22 MHz (USB mode).
"""

def decode_bcd_freq(freq_bytes):
    """Decode 4 packed-BCD bytes to frequency (10 Hz units)."""
    if len(freq_bytes) != 4:
        return None
    
    # Check if all nibbles are valid BCD (0-9)
    for b in freq_bytes:
        high = (b >> 4) & 0x0F
        low = b & 0x0F
        if high > 9 or low > 9:
            return None
    
    # Convert to 8-digit BCD string
    bcd_str = "".join(f"{b:02x}" for b in freq_bytes)
    
    # Interpret as 10 Hz units (MSB-first, e.g., 01817022 = 18.17022 MHz)
    freq_10hz = int(bcd_str)
    
    # Convert back to MHz for display
    freq_mhz = freq_10hz / 100000.0
    
    return freq_10hz, freq_mhz, bcd_str

# Expected frequency: 18.170.22 MHz
expected_mhz = 18.17022
expected_10hz = int(expected_mhz * 100000)
expected_bcd = f"{expected_10hz:08d}"
print(f"Expected frequency: {expected_mhz} MHz = {expected_10hz} (10Hz units)")
print(f"Expected BCD digits: {expected_bcd}")
print(f"Expected BCD bytes (MSB-first): {expected_bcd[0:2]} {expected_bcd[2:4]} {expected_bcd[4:6]} {expected_bcd[6:8]}")
print()

# Actual response from radio: 0C 00 B8 CF 80 00 00 01 11 00 11 11 11 11 11 00
response = bytes.fromhex("0C 00 B8 CF 80 00 00 01 11 00 11 11 11 11 11 00")
print(f"Actual Status Update response ({len(response)} bytes):")
print(" ".join(f"{b:02X}" for b in response))
print()

# Try decoding from different byte positions
print("Attempting to decode frequency from different byte windows:")
print("-" * 80)

for start in range(0, len(response) - 3):
    window = response[start:start+4]
    result = decode_bcd_freq(window)
    
    if result:
        freq_10hz, freq_mhz, bcd_str = result
        match = "✓ MATCH!" if abs(freq_mhz - expected_mhz) < 0.001 else ""
        print(f"Bytes {start:2d}-{start+3:2d} ({' '.join(f'{b:02X}' for b in window)}): "
              f"{freq_mhz:7.5f} MHz ({bcd_str}) {match}")
    else:
        # Show why it failed
        invalid = []
        for i, b in enumerate(window):
            high = (b >> 4) & 0x0F
            low = b & 0x0F
            if high > 9:
                invalid.append(f"byte[{i}] high nibble={high}")
            if low > 9:
                invalid.append(f"byte[{i}] low nibble={low}")
        
        if invalid:
            print(f"Bytes {start:2d}-{start+3:2d} ({' '.join(f'{b:02X}' for b in window)}): Invalid BCD - {', '.join(invalid)}")
        else:
            freq_10hz = int("".join(f"{b:02x}" for b in window))
            freq_mhz = freq_10hz / 100000.0
            print(f"Bytes {start:2d}-{start+3:2d} ({' '.join(f'{b:02X}' for b in window)}): {freq_mhz:7.5f} MHz (not matching)")

print()
print("=" * 80)
print("Expected BCD byte representation of 18.170.22 MHz:")
print(f"  01 81 70 22 (MSB-first, packed BCD)")
print()
