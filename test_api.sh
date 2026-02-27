#!/bin/bash
# Simple API test script using curl
# Tests the Ham Radio Monitor HTTP API

API="http://127.0.0.1:8080/api"

echo "============================================"
echo "Ham Radio Monitor API Test Script"
echo "============================================"
echo ""

# Check if API is available
if ! curl -s "$API/status" > /dev/null 2>&1; then
    echo "✗ ERROR: Cannot connect to API server"
    echo "  Make sure the Ham Radio Monitor is running"
    echo "  and HTTP_API_ENABLED = True in constants.py"
    exit 1
fi

echo "✓ API server is responding"
echo ""

# Test 1: Get Status
echo "--- Test 1: Get Full Status ---"
curl -s "$API/status" | python3 -m json.tool
echo ""
echo ""

# Test 2: Set Frequency
echo "--- Test 2: Set Frequency to 14.074 MHz (20m FT8) ---"
curl -s -X POST "$API/frequency" \
  -H "Content-Type: application/json" \
  -d '{"frequency":"14.074.00"}' | python3 -m json.tool
echo ""
echo ""

# Test 3: Set Mode
echo "--- Test 3: Set Mode to USB ---"
curl -s -X POST "$API/mode" \
  -H "Content-Type: application/json" \
  -d '{"mode":"USB"}' | python3 -m json.tool
echo ""
echo ""

# Test 4: Get Current Frequency
echo "--- Test 4: Get Current Frequency ---"
curl -s "$API/frequency" | python3 -m json.tool
echo ""
echo ""

# Test 5: Enable Split Mode
echo "--- Test 5: Enable Split Mode ---"
curl -s -X POST "$API/split" \
  -H "Content-Type: application/json" \
  -d '{"enable":true}' | python3 -m json.tool
echo ""
echo ""

# Test 6: Set VFO B Frequency
echo "--- Test 6: Set VFO B to 14.250 MHz ---"
curl -s -X POST "$API/frequency" \
  -H "Content-Type: application/json" \
  -d '{"frequency":"14.250.00","vfo":"B"}' | python3 -m json.tool
echo ""
echo ""

# Test 7: Adjust Controls
echo "--- Test 7: Adjust AF Gain and RF Gain ---"
curl -s -X POST "$API/controls" \
  -H "Content-Type: application/json" \
  -d '{"af_gain":75,"rf_gain":90}' | python3 -m json.tool
echo ""
echo ""

# Test 8: Get Controls
echo "--- Test 8: Get All Control Values ---"
curl -s "$API/controls" | python3 -m json.tool
echo ""
echo ""

# Test 9: Disable Split Mode
echo "--- Test 9: Disable Split Mode ---"
curl -s -X POST "$API/split" \
  -H "Content-Type: application/json" \
  -d '{"enable":false}' | python3 -m json.tool
echo ""
echo ""

# Test 10: Final Status
echo "--- Test 10: Final Status Check ---"
curl -s "$API/status" | python3 -m json.tool
echo ""
echo ""

echo "============================================"
echo "All Tests Complete!"
echo "============================================"
