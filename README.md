# Arkadia

Arkadia monitors home environment conditions — temperature, pressure, humidity, CO₂, volatile organic compounds (VOCs), and ambient sound — using sensors connected to a Raspberry Pi 5.  Readings are published to a local MQTT broker, exposed via a REST/WebSocket API, and displayed on a retro-styled web dashboard.

Named after the base camp of the Skaikru in [The 100](https://en.wikipedia.org/wiki/The_100_(TV_series)).

---

## Architecture

```
bme280 ─┐
scd40  ─┤
sgp40  ─┼──► Mosquitto :1883 ──► API :8000 ──► Web dashboard / external consumers
audio  ─┘
              (retained MQTT)    (REST + WebSocket)
```

Sensor services publish retained JSON payloads to a local Mosquitto broker.  The API service subscribes to all sensor topics, maintains the latest readings in memory, and exposes them over HTTP and a WebSocket endpoint for real-time audio streaming.

See [`docs/tech-design.md`](docs/tech-design.md) for the full technical design and [`docs/dev-plan.md`](docs/dev-plan.md) for the implementation history.

---

## Sensors

| Sensor  | Interface | I2C Address | Topic                         | Measurements                        |
|---------|-----------|-------------|-------------------------------|-------------------------------------|
| BME280  | I2C       | `0x76/0x77` | `home/sensors/climate/bme280` | Temperature, humidity, pressure     |
| SCD40   | I2C       | `0x62`      | `home/sensors/air/scd40`      | CO₂, temperature, humidity          |
| SGP40   | I2C       | `0x59`      | `home/sensors/air/sgp40`      | VOC Index (Sensirion scale 1–500)   |
| INMP441 | I2S       | —           | `home/sensors/audio/inmp441`  | Ambient sound (RMS / dBFS)          |

The audio service also publishes a real-time stream at `home/sensors/audio/inmp441/stream` (QoS 0, non-retained, 20 Hz) for the WebSocket visualizer.

All sensors publish an online/offline status to `home/status/{sensor_id}` via MQTT Last Will and Testament.

---

## Repository Structure

```
arkadia/
├── common/                    # Shared library (config, models, MQTT, I2C)
│   ├── config.py              # TOML loader, global+local merge
│   ├── models.py              # Pydantic payload models for all sensors
│   ├── mqtt.py                # paho-mqtt wrapper, LWT, structured logging
│   └── i2c.py                 # I2C base class
│
├── services/
│   ├── bme280/                # Climate sensor (temperature, humidity, pressure)
│   ├── scd40/                 # CO₂ sensor
│   ├── sgp40/                 # VOC sensor
│   ├── audio/                 # I2S microphone (summary + real-time stream)
│   └── api/                   # FastAPI REST + WebSocket service
│
├── web/                       # Svelte + Vite web dashboard
│   └── src/
│       ├── App.svelte         # Three-panel dashboard with polling + WebSocket
│       ├── api.js             # API client, thresholds, audio stream
│       └── components/        # Header, SensorCard, ReadingRow, TemperatureGauge,
│                              # BarMeter, VocIndicator, EQVisualizer, WaveformScope
│
├── config/
│   └── global.toml            # Shared broker and logging defaults
├── mosquitto/
│   └── mosquitto.conf         # Broker: localhost-only, anonymous, persistence
├── scripts/
│   ├── setup.sh               # First-time system setup (packages, venvs, I2C/I2S)
│   └── deploy.sh              # Deploy / restart all services
├── skills/
│   └── pi-deployment.md       # SOP for deploying and debugging on the Pi
├── tests/                     # Unit tests — no hardware required
└── pyproject.toml
```

---

## Deploying on Raspberry Pi

### First-time setup

```bash
git clone https://github.com/malonge/Arkadia
cd Arkadia
sudo bash scripts/setup.sh
```

`setup.sh` handles everything in one pass:
- Installs system packages (`mosquitto`, `python3-venv`, `i2c-tools`, `nodejs`, etc.)
- Configures and starts Mosquitto
- Enables I2C via `raspi-config`
- Configures I2S for the INMP441 microphone in `/boot/firmware/config.txt`
- Creates a Python virtualenv for each service and installs its dependencies
- Scaffolds `/etc/home-monitor.env` with `ARKADIA_ROOT` and a placeholder `MONITOR_API_KEY`

After setup, set a real API key:

```bash
sudo nano /etc/home-monitor.env
# Set MONITOR_API_KEY to a strong random value, e.g.:
# python3 -c "import secrets; print(secrets.token_hex(32))"
```

If the I2S lines were added to `/boot/firmware/config.txt`, reboot before continuing.

### Deploy

```bash
sudo bash scripts/deploy.sh
```

Copies unit files, fixes `User=` to the actual username, enables all services, and starts them in dependency order (`mosquitto` → sensors → `api`).  Safe to re-run after any code or config change.

### Verify all services are up

```bash
systemctl status bme280 scd40 sgp40 audio api
journalctl -u sgp40 -f          # follow logs for one service
mosquitto_sub -h 127.0.0.1 -t 'home/sensors/#' -v    # watch all readings
mosquitto_sub -h 127.0.0.1 -t 'home/status/#' -v     # watch connectivity
i2cdetect -y 1                  # should show 0x59, 0x62, 0x76/0x77
```

For detailed per-service deployment steps and troubleshooting, see [`skills/pi-deployment.md`](skills/pi-deployment.md).

---

## Web Dashboard

The dashboard is a Svelte + Vite app served from the API at `http://<pi>:8000/` (after PR 12 merges; during development, run it separately on port 5173).

**Development (SSH tunnel from your Mac):**

```bash
# Mac terminal — forward both ports
ssh -L 5173:localhost:5173 -L 8000:localhost:8000 micheldelving@<pi-ip>

# Pi terminal — start the dev server
cd ~/Projects/Arkadia/web
npm install       # first time only
npm run dev
```

Open `http://localhost:5173` in your browser.  The first load shows a settings modal — enter your `MONITOR_API_KEY`.

**Panels:**

| Panel | Sensor | Displays |
|-------|--------|---------|
| CLIMATE | BME280 | Temperature gauge (16 pixel blocks, color-coded) + humidity + pressure |
| AIR QUALITY | SCD40 + SGP40 | CO₂ bar meter + temperature/humidity; VOC Index with color indicator |
| AUDIO | INMP441 | 8-band EQ visualizer (canvas, peak-hold) + waveform oscilloscope + RMS level |

The header shows a live clock, date, and hardcoded location coordinates.  All readings have LED color indicators (green → lime → amber → red) based on health thresholds.

---

## API

Base URL: `http://<pi-hostname>:8000`

All endpoints except `/health` require `X-API-Key: <key>` (set in `/etc/home-monitor.env`).

| Method    | Path                          | Description                              |
|-----------|-------------------------------|------------------------------------------|
| GET       | `/health`                     | Broker connectivity and uptime (no auth) |
| GET       | `/version`                    | Service version and git commit           |
| GET       | `/sensors`                    | Latest readings from all sensors         |
| GET       | `/sensors/{sensor_id}`        | Latest reading for one sensor (200/404/503) |
| GET       | `/sensors/{sensor_id}/status` | Staleness + connectivity metadata        |
| WebSocket | `/ws/audio/stream`            | Real-time `AudioStreamPayload` at ~20 Hz |

WebSocket authentication: `?api_key=<key>` query parameter.

---

## Development Quick Start

Run the unit tests on any machine — no hardware required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest ruff
pytest          # 283 tests, all pass without hardware
ruff check .    # linting
```

---

## Configuration

| File | Purpose |
|------|---------|
| `config/global.toml` | Shared broker host/port and logging defaults |
| `services/<name>/config.toml` | Per-service sensor settings and MQTT topic |
| `/etc/home-monitor.env` | `ARKADIA_ROOT` path and `MONITOR_API_KEY` secret |
