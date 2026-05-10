# Arkadia

Arkadia monitors home environment conditions — temperature, pressure, humidity, CO₂, and ambient sound — using sensors connected to a Raspberry Pi 5.

Named after the base camp of the Skaikru in [The 100](https://en.wikipedia.org/wiki/The_100_(TV_series)).

---

## Architecture

Sensor services publish JSON payloads to a local Mosquitto MQTT broker. An API service subscribes to all sensor topics, maintains the latest readings in memory, and exposes them over a REST API.

```
bme280 ─┐
scd40  ─┼──► Mosquitto :1883 ──► API :8000 ──► External consumers
audio  ─┘
```

See [`docs/tech-design.md`](docs/tech-design.md) for the full technical design.

---

## Repository Structure

```
arkadia/
├── common/            # Shared library (config, models, MQTT, I2C)
├── services/
│   ├── bme280/        # Temperature / humidity / pressure service
│   ├── scd40/         # CO₂ service
│   ├── audio/         # Ambient sound service
│   └── api/           # REST API service
├── config/
│   └── global.toml    # Shared broker and logging defaults
├── mosquitto/
│   └── mosquitto.conf # Broker configuration
├── scripts/
│   ├── setup.sh       # First-time system setup
│   └── deploy.sh      # Service deployment / restart
├── tests/             # Unit tests (no hardware required)
└── pyproject.toml
```

---

## Quick Start

### Install the shared library

```bash
pip install -e .
```

### Run the tests

```bash
pip install pytest
pytest
```

---

## Sensors

| Sensor  | Interface | Topic                         | Measurements                        |
|---------|-----------|-------------------------------|-------------------------------------|
| BME280  | I2C       | `home/sensors/climate/bme280` | Temperature, humidity, pressure     |
| SCD40   | I2C       | `home/sensors/air/scd40`      | CO₂                                 |
| INMP441 | I2S       | `home/sensors/audio/inmp441`  | Ambient sound (RMS / dBFS)          |

---

## Setup and Deploy

```bash
sudo bash scripts/setup.sh   # Install system packages and create virtualenvs
sudo bash scripts/deploy.sh  # Install and start systemd services
```

### Mosquitto smoke test

After running `setup.sh`, verify the broker with a publish/subscribe round-trip:

```bash
# Terminal 1 — subscribe
mosquitto_sub -h 127.0.0.1 -t 'test/#' -v

# Terminal 2 — publish
mosquitto_pub -h 127.0.0.1 -t 'test/hello' -m 'world'
```

Expected output in terminal 1:

```
test/hello world
```

Verify that connections from outside localhost are refused (replace `<pi-ip>` with the Pi's LAN address):

```bash
mosquitto_pub -h <pi-ip> -t 'test/hello' -m 'world'
# Expected: Connection refused
```

View broker logs:

```bash
journalctl -u mosquitto -f
```

---

## Configuration

- Global defaults: `config/global.toml`
- Per-service overrides: `services/<name>/config.toml`
- Secrets: `/etc/home-monitor.env` (created by `setup.sh`)

---

## API

Base URL: `http://<pi-hostname>:8000`

| Method | Path                          | Description                     |
|--------|-------------------------------|---------------------------------|
| GET    | `/health`                     | Broker connectivity and uptime  |
| GET    | `/version`                    | Service version and git commit  |
| GET    | `/sensors`                    | Latest readings from all sensors|
| GET    | `/sensors/{sensor_id}`        | Latest reading for one sensor   |
| GET    | `/sensors/{sensor_id}/status` | Staleness metadata              |

All endpoints except `/health` require an `X-API-Key` header.
