#!/usr/bin/env python3
"""
Simple test script for Ham Radio Monitor HTTP API
Demonstrates basic API usage
"""

import requests
import time
import json

API_BASE = "http://127.0.0.1:8080/api"

def print_status():
    """Get and display full radio status"""
    print("\n" + "="*60)
    print("RADIO STATUS")
    print("="*60)
    
    response = requests.get(f"{API_BASE}/status")
    if response.status_code == 200:
        data = response.json()
        print(f"VFO A: {data['frequency_a']} - {data['mode_a']}")
        print(f"VFO B: {data['frequency_b']} - {data['mode_b']}")
        print(f"Active VFO: {data['active_vfo']}")
        print(f"Split: {'ON' if data['split_enabled'] else 'OFF'}")
        print(f"Transmitting: {'YES' if data['transmitting'] else 'NO'}")
        print(f"AF Gain: {data['af_gain']}  RF Gain: {data['rf_gain']}  Power: {data['power_level']}")
        print(f"Meter Level: {int(data['meter_level'])}")
        print(f"Memory: {data['selected_memory']}")
    else:
        print(f"Error: {response.status_code}")
    print("="*60)

def set_frequency(freq, vfo="A"):
    """Set frequency"""
    print(f"\nSetting VFO {vfo} to {freq}...")
    response = requests.post(f"{API_BASE}/frequency", 
                            json={"frequency": freq, "vfo": vfo})
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Set to {data['frequency']}")
    else:
        print(f"✗ Error: {response.text}")

def set_mode(mode, vfo="A"):
    """Set mode"""
    print(f"\nSetting VFO {vfo} to {mode}...")
    response = requests.post(f"{API_BASE}/mode",
                            json={"mode": mode, "vfo": vfo})
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Set to {data['mode']}")
    else:
        print(f"✗ Error: {response.text}")

def toggle_split(enable):
    """Toggle split mode"""
    state = "ON" if enable else "OFF"
    print(f"\nTurning split mode {state}...")
    response = requests.post(f"{API_BASE}/split",
                            json={"enable": enable})
    if response.status_code == 200:
        print(f"✓ Split mode: {state}")
    else:
        print(f"✗ Error: {response.text}")

def set_controls(af_gain=None, rf_gain=None, power=None):
    """Set control values"""
    print(f"\nAdjusting controls...")
    data = {}
    if af_gain is not None:
        data['af_gain'] = af_gain
    if rf_gain is not None:
        data['rf_gain'] = rf_gain
    if power is not None:
        data['power_level'] = power
    
    response = requests.post(f"{API_BASE}/controls", json=data)
    if response.status_code == 200:
        result = response.json()
        print(f"✓ Updated: {result['updated']}")
    else:
        print(f"✗ Error: {response.text}")

def run_demo():
    """Run a full demonstration of the API"""
    print("\n" + "#"*60)
    print("# Ham Radio Monitor API Demo")
    print("#"*60)
    
    try:
        # Initial status
        print_status()
        time.sleep(1)
        
        # Change to 20m FT8
        print("\n--- Test 1: Change to 20m FT8 ---")
        set_frequency("14.074.00")
        set_mode("USB")
        time.sleep(1)
        print_status()
        
        # Change to 40m CW
        print("\n--- Test 2: Change to 40m CW ---")
        set_frequency("7.030.00")
        set_mode("CW")
        time.sleep(1)
        print_status()
        
        # Enable split operation
        print("\n--- Test 3: Enable Split Mode ---")
        set_frequency("14.250.00", "B")
        toggle_split(True)
        time.sleep(1)
        print_status()
        
        # Adjust controls
        print("\n--- Test 4: Adjust Gains ---")
        set_controls(af_gain=75, rf_gain=90, power=50)
        time.sleep(1)
        print_status()
        
        # Disable split
        print("\n--- Test 5: Disable Split Mode ---")
        toggle_split(False)
        time.sleep(1)
        print_status()
        
        print("\n" + "#"*60)
        print("# Demo Complete!")
        print("#"*60)
        
    except requests.exceptions.ConnectionError:
        print("\n✗ ERROR: Cannot connect to API server")
        print("  Make sure the Ham Radio Monitor application is running")
        print("  and HTTP_API_ENABLED = True in constants.py")
    except Exception as e:
        print(f"\n✗ ERROR: {e}")

if __name__ == "__main__":
    run_demo()
