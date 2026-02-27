# Ham Radio Monitor - HTTP API Documentation

The Ham Radio Monitor includes a built-in HTTP REST API for remote control and monitoring. This allows external applications, scripts, or web interfaces to interact with the radio.

## Configuration

API settings are in `constants.py`:

```python
HTTP_API_ENABLED = True       # Enable/disable API server
HTTP_API_PORT = 8080          # Port number
HTTP_API_HOST = "127.0.0.1"   # Localhost only (secure)
```

**Security Note:** Default binding is `127.0.0.1` (localhost only). To allow network access, change to `"0.0.0.0"`, but be aware this exposes the API to your network.

## Base URL

```
http://127.0.0.1:8080/api
```

## API Endpoints

### GET Endpoints

#### Get Full Radio Status
```bash
GET /api/status
```

**Response:**
```json
{
  "success": true,
  "frequency_a": "14.320.00",
  "frequency_b": "18.120.00",
  "mode_a": "USB",
  "mode_b": "LSB",
  "active_vfo": "A",
  "transmitting": false,
  "split_enabled": false,
  "af_gain": 50,
  "sub_af_gain": 50,
  "rf_gain": 80,
  "power_level": 100,
  "shift": 50,
  "width": 50,
  "notch": 50,
  "antenna": 1,
  "tuner_active": false,
  "meter_level": 125.5,
  "mock_mode": true,
  "selected_memory": 0
}
```

**Example:**
```bash
curl http://127.0.0.1:8080/api/status
```

---

#### Get Current Frequency
```bash
GET /api/frequency
```

**Response:**
```json
{
  "success": true,
  "frequency": "14.320.00"
}
```

Returns frequency of the active VFO.

---

#### Get Current Mode
```bash
GET /api/mode
```

**Response:**
```json
{
  "success": true,
  "mode": "USB"
}
```

Returns mode of the active VFO. Valid modes: `LSB`, `USB`, `CW`, `AM`, `FM`.

---

#### Get Active VFO
```bash
GET /api/vfo
```

**Response:**
```json
{
  "success": true,
  "active_vfo": "A"
}
```

---

#### Get Split Mode Status
```bash
GET /api/split
```

**Response:**
```json
{
  "success": true,
  "split_enabled": false
}
```

---

#### Get Memory Channel
```bash
GET /api/memory/:id
```

**Parameters:**
- `:id` - Memory channel number (0-9)

**Response:**
```json
{
  "success": true,
  "channel": 0,
  "memory": {
    "freq_a": "14.320.00",
    "mode_a": "USB",
    "freq_b": "18.120.00",
    "mode_b": "LSB"
  }
}
```

**Example:**
```bash
curl http://127.0.0.1:8080/api/memory/0
```

---

#### Get All Control Values
```bash
GET /api/controls
```

**Response:**
```json
{
  "success": true,
  "af_gain": 50,
  "sub_af_gain": 50,
  "rf_gain": 80,
  "power_level": 100,
  "shift": 50,
  "width": 50,
  "notch": 50
}
```

---

### POST Endpoints

#### Set Frequency
```bash
POST /api/frequency
```

**Request Body:**
```json
{
  "frequency": "14.074.00",
  "vfo": "A"
}
```

**Parameters:**
- `frequency` (required) - Frequency in format "XX.XXX.XX"
- `vfo` (optional) - VFO to set ("A" or "B"), defaults to active VFO

**Response:**
```json
{
  "success": true,
  "frequency": "14.074.00",
  "vfo": "A"
}
```

**Example:**
```bash
curl -X POST http://127.0.0.1:8080/api/frequency \
  -H "Content-Type: application/json" \
  -d '{"frequency":"14.074.00"}'
```

---

#### Set Mode
```bash
POST /api/mode
```

**Request Body:**
```json
{
  "mode": "CW",
  "vfo": "A"
}
```

**Parameters:**
- `mode` (required) - One of: `LSB`, `USB`, `CW`, `AM`, `FM`
- `vfo` (optional) - VFO to set ("A" or "B"), defaults to active VFO

**Response:**
```json
{
  "success": true,
  "mode": "CW",
  "vfo": "A"
}
```

**Example:**
```bash
curl -X POST http://127.0.0.1:8080/api/mode \
  -H "Content-Type: application/json" \
  -d '{"mode":"CW"}'
```

---

#### Switch VFO
```bash
POST /api/vfo
```

**Request Body:**
```json
{
  "vfo": "B"
}
```

**Parameters:**
- `vfo` (required) - VFO to activate ("A" or "B")

**Response:**
```json
{
  "success": true,
  "active_vfo": "B"
}
```

**Example:**
```bash
curl -X POST http://127.0.0.1:8080/api/vfo \
  -H "Content-Type: application/json" \
  -d '{"vfo":"B"}'
```

---

#### Toggle Split Mode
```bash
POST /api/split
```

**Request Body:**
```json
{
  "enable": true
}
```

**Parameters:**
- `enable` (optional) - `true` or `false`. If omitted, toggles current state.

**Response:**
```json
{
  "success": true,
  "split_enabled": true
}
```

**Example:**
```bash
# Enable split mode
curl -X POST http://127.0.0.1:8080/api/split \
  -H "Content-Type: application/json" \
  -d '{"enable":true}'

# Toggle split mode
curl -X POST http://127.0.0.1:8080/api/split \
  -H "Content-Type: application/json" \
  -d '{}'
```

---

#### Toggle Transmit
```bash
POST /api/transmit
```

**Request Body:**
```json
{
  "enable": true
}
```

**Parameters:**
- `enable` (optional) - `true` or `false`. If omitted, toggles current state.

**Response:**
```json
{
  "success": true,
  "transmitting": true
}
```

**Example:**
```bash
curl -X POST http://127.0.0.1:8080/api/transmit \
  -H "Content-Type: application/json" \
  -d '{"enable":true}'
```

---

#### Set Control Values
```bash
POST /api/controls
```

**Request Body:**
```json
{
  "af_gain": 75,
  "rf_gain": 90,
  "power_level": 50
}
```

**Parameters:** (all optional, include only what you want to change)
- `af_gain` - Audio gain (0-100)
- `sub_af_gain` - Sub audio gain/VFO B volume (0-100)
- `rf_gain` - RF gain (0-100)
- `power_level` - Transmit power (0-100)
- `shift` - IF shift (0-100)
- `width` - Filter width (0-100)
- `notch` - Notch filter (0-100)

**Response:**
```json
{
  "success": true,
  "updated": {
    "af_gain": 75,
    "rf_gain": 90,
    "power_level": 50
  }
}
```

**Example:**
```bash
curl -X POST http://127.0.0.1:8080/api/controls \
  -H "Content-Type: application/json" \
  -d '{"af_gain":75,"rf_gain":90}'
```

---

#### Store to Memory Channel
```bash
POST /api/memory/:id/store
```

**Parameters:**
- `:id` - Memory channel number (0-9)

Stores current VFO A and VFO B frequencies and modes to the specified memory channel.

**Response:**
```json
{
  "success": true,
  "message": "Stored to memory 0"
}
```

**Example:**
```bash
curl -X POST http://127.0.0.1:8080/api/memory/0/store \
  -H "Content-Type: application/json"
```

---

### PUT Endpoints

#### Recall from Memory Channel
```bash
PUT /api/memory/:id
```

**Parameters:**
- `:id` - Memory channel number (0-9)

Recalls frequencies and modes from the specified memory channel.

**Response:**
```json
{
  "success": true,
  "message": "Recalled memory 0"
}
```

**Example:**
```bash
curl -X PUT http://127.0.0.1:8080/api/memory/0
```

---

## Error Responses

All endpoints return error responses in this format:

```json
{
  "error": "Error message description",
  "success": false
}
```

**HTTP Status Codes:**
- `200` - Success
- `400` - Bad request (invalid parameters)
- `404` - Endpoint not found
- `500` - Internal server error

---

## CORS Support

The API includes CORS headers, allowing access from web browsers:

```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, PUT, OPTIONS
Access-Control-Allow-Headers: Content-Type
```

---

## Usage Examples

### Python Example

```python
import requests

# Get status
response = requests.get('http://127.0.0.1:8080/api/status')
status = response.json()
print(f"Frequency: {status['frequency_a']}")
print(f"Mode: {status['mode_a']}")

# Set frequency to 7.074 MHz (FT8 on 40m)
requests.post('http://127.0.0.1:8080/api/frequency',
              json={'frequency': '7.074.00'})

# Set mode to USB
requests.post('http://127.0.0.1:8080/api/mode',
              json={'mode': 'USB'})

# Enable split mode
requests.post('http://127.0.0.1:8080/api/split',
              json={'enable': True})
```

### JavaScript Example

```javascript
// Get status
fetch('http://127.0.0.1:8080/api/status')
  .then(response => response.json())
  .then(data => {
    console.log('Frequency:', data.frequency_a);
    console.log('Mode:', data.mode_a);
  });

// Set frequency
fetch('http://127.0.0.1:8080/api/frequency', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ frequency: '14.074.00' })
})
  .then(response => response.json())
  .then(data => console.log('Success:', data));

// Store to memory
fetch('http://127.0.0.1:8080/api/memory/0/store', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' }
})
  .then(response => response.json())
  .then(data => console.log('Stored:', data));
```

### Bash Script Example

```bash
#!/bin/bash
API="http://127.0.0.1:8080/api"

# Quick band change function
change_band() {
    local freq=$1
    local mode=$2
    curl -s -X POST "$API/frequency" \
        -H "Content-Type: application/json" \
        -d "{\"frequency\":\"$freq\"}"
    curl -s -X POST "$API/mode" \
        -H "Content-Type: application/json" \
        -d "{\"mode\":\"$mode\"}"
    echo "Changed to $freq $mode"
}

# Quick band presets
case "$1" in
    "80m") change_band "3.573.00" "LSB" ;;
    "40m") change_band "7.074.00" "USB" ;;
    "20m") change_band "14.074.00" "USB" ;;
    "17m") change_band "18.100.00" "USB" ;;
    "15m") change_band "21.074.00" "USB" ;;
    "10m") change_band "28.074.00" "USB" ;;
    *) echo "Usage: $0 {80m|40m|20m|17m|15m|10m}" ;;
esac
```

---

## Integration Ideas

1. **Web Dashboard** - Create a web UI to monitor/control the radio from any device
2. **Band Hopping Script** - Automatically scan through different bands
3. **Logging Application** - Record frequency changes and QSOs
4. **Contest Mode** - Rapid frequency/mode changes via keyboard macros
5. **Remote Control** - Control radio from another computer on network
6. **FT8/Digital Mode Integration** - Coordinate with WSJT-X or similar
7. **Alerting** - Monitor S-meter and alert on strong signals
8. **Voice Control** - Use speech recognition to change frequency/mode

---

## Testing the API

Use the included test script or try these quick tests:

```bash
# Test 1: Get complete status
curl http://127.0.0.1:8080/api/status | python3 -m json.tool

# Test 2: Set frequency to FT8 on 20m
curl -X POST http://127.0.0.1:8080/api/frequency \
  -H "Content-Type: application/json" \
  -d '{"frequency":"14.074.00"}' | python3 -m json.tool

# Test 3: Change to CW mode
curl -X POST http://127.0.0.1:8080/api/mode \
  -H "Content-Type: application/json" \
  -d '{"mode":"CW"}' | python3 -m json.tool

# Test 4: Enable split operation
curl -X POST http://127.0.0.1:8080/api/split \
  -H "Content-Type: application/json" \
  -d '{"enable":true}' | python3 -m json.tool

# Test 5: Adjust gains
curl -X POST http://127.0.0.1:8080/api/controls \
  -H "Content-Type: application/json" \
  -d '{"af_gain":80,"rf_gain":100}' | python3 -m json.tool
```

---

## Troubleshooting

**API not responding:**
- Check `HTTP_API_ENABLED = True` in `constants.py`
- Verify port 8080 is not in use: `lsof -i :8080`
- Check console for "HTTP API server started" message

**Connection refused:**
- Ensure app is running
- Check firewall settings
- Verify correct host/port in request

**CORS errors in browser:**
- API includes CORS headers, should work from any origin
- If issues persist, check browser console for specific error

---

## Security Considerations

- **Default:** API binds to `127.0.0.1` (localhost only) - safe for single-user systems
- **Network Access:** Changing to `0.0.0.0` exposes API to network - use with caution
- **No Authentication:** API has no authentication - suitable for trusted environments only
- **Trusted Networks:** Only expose on trusted networks, never the public internet
- **Firewall:** Consider firewall rules if exposing beyond localhost

---

73!
