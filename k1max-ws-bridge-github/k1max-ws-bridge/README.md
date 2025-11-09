# K1/K1 Max WebSocket → MQTT Bridge

This Home Assistant add-on connects directly to a **Creality K1 / K1 Max** printer’s WebSocket
and publishes real-time values to Home Assistant via **MQTT Discovery** (progress, time remaining,
temps, layers, position, etc.).

## Features
- Real-time nozzle & bed temperature
- Time remaining / elapsed
- Print progress
- Layers, XYZ position, material used
- MQTT Discovery: entities appear automatically

## Install (GitHub Repository)
1. Create a repo with this folder structure (or use this ZIP as-is).
2. In Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories** → add your repo URL.
3. Install **K1/K1 Max WebSocket → MQTT Bridge** from the “Local add-ons” / custom repo list.
4. Configure and start.

### Minimal Configuration
```yaml
ws_url: "ws://192.168.0.41/websocket"
mqtt:
  host: "core-mosquitto"
  port: 1883
  username: "homeassistant"
  password: "YOUR_MQTT_PASSWORD"
```

### Entities (examples)
- `sensor.k1max_time_left`
- `sensor.k1max_time_elapsed`
- `sensor.k1max_progress`
- `sensor.k1max_nozzle_temp`
- `sensor.k1max_bed_temp`
- `sensor.k1max_layer`
- `sensor.k1max_total_layers`
- `sensor.k1max_position`
- `sensor.k1max_used_material_mm`

## Troubleshooting
- **Logs**: Supervisor → Add-ons → this add-on → Logs
- Ensure printer WebSocket is reachable from HA.
- Temporarily enable raw frame logging:
```yaml
debug:
  log_raw_frames: true
  raw_frames_limit: 5
```

## License
MIT — see LICENSE.
