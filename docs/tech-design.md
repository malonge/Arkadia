# Home Environment Monitor — Technical Design Document

**Version:** 1.1  
**Platform:** Raspberry Pi 5  
**Last Updated:** May 2026

---

## Table of Contents

1. Overview
2. Hardware
3. System Architecture
4. Repository Structure
5. Service Definitions
6. Data Models & MQTT Schema
7. REST API Specification
8. Configuration
9. Shared Library (`common/`)
10. Deployment & Orchestration
11. Observability
12. Security Model
13. Design Principles & Decisions
14. Future Extensibility

---

# Overview

This system monitors environmental conditions in the home using sensors connected to a Raspberry Pi 5.

Sensor services collect measurements and publish them to a local MQTT broker. An API service subscribes to all sensor topics, maintains the latest state in memory, and exposes that state over a REST API.

The REST API is the single external interface for all consumers, including:

- Web dashboards
- Mobile applications
- Home automation systems
- Grafana
- Third-party integrations

## Design Philosophy

- Simple and correct over clever.
- Each process has a single responsibility.
- Services fail fast on startup errors.
- systemd handles process supervision and restart.
- Configuration lives outside of code.
- All inter-process communication is local to the Raspberry Pi.
- Adding a new sensor requires minimal changes.

---

# Hardware

| Sensor | Interface | Measurements |
|------|------|------|
| BME280 | I2C | Temperature, humidity, pressure |
| SCD40 | I2C | CO₂ concentration |
| INMP441 | I2S | Ambient sound level |

**Host Platform:** Raspberry Pi 5  
**Operating System:** Raspberry Pi OS (64-bit, Bookworm)

---

# System Architecture

```text
┌─────────────────────────────────────────────────────────┐
│                     Raspberry Pi 5                      │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │  bme280  │  │  scd40   │  │  audio   │              │
│  │ service  │  │ service  │  │ service  │              │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│       │              │              │                  │
│       └──────────────┼──────────────┘                  │
│                      │ MQTT publish                    │
│                      ▼                                 │
│             ┌─────────────────┐                       │
│             │   Mosquitto     │                       │
│             │  localhost:1883 │                       │
│             └────────┬────────┘                       │
│                      │ MQTT subscribe                  │
│                      ▼                                 │
│             ┌─────────────────┐                       │
│             │   API service   │                       │
│             │ FastAPI :8000   │                       │
│             │ In-memory cache │                       │
│             └────────┬────────┘                       │
│                      │                                 │
└──────────────────────┼─────────────────────────────────┘
                       │ HTTP / REST
                       ▼
                External Consumers
```

## Process Inventory

| Process | Type | Managed By |
|------|------|------|
| `mosquitto` | MQTT broker | systemd |
| `bme280` | Python service | systemd |
| `scd40` | Python service | systemd |
| `audio` | Python service | systemd |
| `api` | FastAPI service | systemd |

---

# Repository Structure

```text
home-monitor/
│
├── common/
│   ├── __init__.py
│   ├── mqtt.py
│   ├── config.py
│   ├── models.py
│   └── i2c.py
│
├── services/
│   ├── bme280/
│   │   ├── main.py
│   │   ├── sensor.py
│   │   ├── config.toml
│   │   └── bme280.service
│   │
│   ├── scd40/
│   │   ├── main.py
│   │   ├── sensor.py
│   │   ├── config.toml
│   │   └── scd40.service
│   │
│   ├── audio/
│   │   ├── main.py
│   │   ├── sensor.py
│   │   ├── config.toml
│   │   └── audio.service
│   │
│   └── api/
│       ├── main.py
│       ├── store.py
│       ├── routes/
│       │   ├── sensors.py
│       │   ├── health.py
│       │   └── version.py
│       ├── config.toml
│       └── api.service
│
├── config/
│   └── global.toml
│
├── scripts/
│   ├── setup.sh
│   └── deploy.sh
│
├── mosquitto/
│   └── mosquitto.conf
│
├── pyproject.toml
└── README.md
```

---

# Service Definitions

## Sensor Service Pattern

Each sensor service follows the same lifecycle:

1. Load configuration.
2. Initialize logging.
3. Connect to MQTT.
4. Initialize hardware.
5. Enter polling loop.
6. Publish readings.
7. Sleep until the next interval.

If initialization fails, the service exits with a non-zero status and systemd restarts it.

### Polling Loop

```text
load config
initialize MQTT
initialize sensor
loop forever:
    collect N samples
    aggregate samples
    build payload
    publish to MQTT (QoS 1, retain=true)
    sleep(interval)
```

### Concurrency Model

Sensor services are synchronous and single-threaded.

- Sensor reads are blocking.
- MQTT uses `loop_start()` to run the network loop in a background thread.
- No asyncio is used.

---

## BME280 Service

**Responsibility:** Measure temperature, humidity, and pressure.

- Interface: I2C
- Library: `adafruit-circuitpython-bme280`
- Topic: `home/sensors/climate/bme280`
- Interval: 30 seconds
- Aggregation: Median of 5 samples

---

## SCD40 Service

**Responsibility:** Measure CO₂ concentration.

- Interface: I2C
- Library: `adafruit-circuitpython-scd4x`
- Topic: `home/sensors/air/scd40`
- Interval: 60 seconds
- Aggregation: Median of 3 samples

---

## Audio Service

**Responsibility:** Measure ambient sound level.

- Interface: I2S
- Library: `sounddevice` or ALSA wrapper
- Topic: `home/sensors/audio/inmp441`
- Interval: 5 seconds
- Aggregation: RMS over the sample window

---

## API Service

**Responsibility:** Subscribe to sensor topics and expose the latest readings over HTTP.

- Framework: FastAPI
- Port: 8000
- MQTT Subscription: `home/sensors/#`

### Internal Components

- MQTT client
- Thread-safe in-memory state store
- HTTP routes

### State Store

The state store is a dictionary keyed by `sensor_id`, protected by a `threading.Lock`.

### Startup Behavior

When the API service connects to MQTT, the broker immediately delivers retained sensor messages. The API therefore reconstructs its state immediately after startup.

---

# Data Models & MQTT Schema

All MQTT payloads are JSON and validated using shared Pydantic models.

## Topic Structure

```text
home/sensors/{category}/{sensor_id}
```

Examples:

- `home/sensors/climate/bme280`
- `home/sensors/air/scd40`
- `home/sensors/audio/inmp441`

## Publish Semantics

All sensor messages are published with:

- QoS: `1`
- Retain: `true`

This ensures the latest reading is persisted by the broker and delivered to subscribers on connection.

## Standard Payload Structure

```json
{
  "schema_version": 1,
  "sensor_id": "bme280",
  "timestamp": "2026-05-08T14:23:01Z",
  "readings": {
    "temperature_c": 21.4
  },
  "meta": {
    "sample_count": 5,
    "aggregation": "median"
  },
  "diagnostics": {
    "uptime_seconds": 12345,
    "read_failures": 0
  }
}
```

### Fields

| Field | Required | Description |
|------|------|------|
| `schema_version` | Yes | Payload schema version |
| `sensor_id` | Yes | Unique sensor identifier |
| `timestamp` | Yes | UTC ISO 8601 timestamp |
| `readings` | Yes | Measurement values |
| `meta` | Yes | Aggregation metadata |
| `diagnostics` | No | Service diagnostics |

---

# REST API Specification

**Base URL:** `http://<pi-hostname>:8000`

## Authentication

Requests must include:

```http
X-API-Key: <key>
```

The API key is stored in an environment variable.

## Endpoints

### `GET /health`

Returns process and broker health.

```json
{
  "status": "ok",
  "broker_connected": true,
  "uptime_seconds": 3821
}
```

---

### `GET /version`

Returns deployment metadata.

```json
{
  "service": "home-monitor-api",
  "version": "1.1.0",
  "git_commit": "abc1234"
}
```

---

### `GET /sensors`

Returns the latest reading from all sensors.

---

### `GET /sensors/{sensor_id}`

Returns the latest reading for a single sensor.

#### Responses

- `200 OK` — Reading available.
- `404 Not Found` — Unknown sensor ID.
- `503 Service Unavailable` — Known sensor but no data received.

---

### `GET /sensors/{sensor_id}/status`

Returns sensor freshness and staleness information.

```json
{
  "sensor_id": "bme280",
  "last_seen": "2026-05-08T14:23:01Z",
  "seconds_since_update": 14,
  "stale": false,
  "stale_threshold_seconds": 120
}
```

---

# Configuration

Configuration is stored in TOML files.

- `config/global.toml` contains shared settings.
- Each service contains a local `config.toml`.
- Service configuration overrides global values.
- Secrets are provided through environment variables.

## Global Configuration

```toml
[broker]
host = "localhost"
port = 1883
keepalive = 60

[logging]
level = "INFO"
format = "json"
```

## Example Sensor Configuration

```toml
[sensor]
i2c_bus = 1
i2c_address = 0x76
sample_count = 5
interval_seconds = 30

[mqtt]
topic = "home/sensors/climate/bme280"
client_id = "bme280-service"
qos = 1
retain = true
```

## Example API Configuration

```toml
[server]
host = "0.0.0.0"
port = 8000

[mqtt]
client_id = "api-service"
subscription = "home/sensors/#"

[sensors]
stale_threshold_seconds = 120

[auth]
api_key_env = "MONITOR_API_KEY"
```

---

# Shared Library (`common/`)

## `common/mqtt.py`

Provides:

- MQTT client initialization
- Auto-reconnect
- Last Will configuration (optional)
- Structured logging
- `publish()` and `subscribe()` helpers

## `common/config.py`

Provides:

- TOML loading
- Config merging
- Validation
- Typed config objects

## `common/models.py`

Provides:

- Shared Pydantic models
- Payload serialization and validation

## `common/i2c.py`

Provides:

- I2C initialization helpers
- Common error handling

---

# Deployment & Orchestration

## First-Time Setup

```bash
sudo bash scripts/setup.sh
```

Responsibilities:

- Install system packages.
- Enable I2C and I2S.
- Create Python virtual environments.
- Install dependencies.
- Install Mosquitto configuration.
- Create `/etc/home-monitor.env`.

## Deploy / Update

```bash
sudo bash scripts/deploy.sh
```

Responsibilities:

- Copy `.service` files.
- Reload systemd.
- Enable services.
- Restart services.

---

## systemd Unit Template

```ini
[Unit]
Description=BME280 Climate Sensor Service
After=mosquitto.service
Requires=mosquitto.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/home-monitor/services/bme280
ExecStart=/home/pi/home-monitor/services/bme280/.venv/bin/python main.py
Restart=on-failure
RestartSec=5
EnvironmentFile=/etc/home-monitor.env
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
```

---

# Observability

All services emit structured JSON logs.

## Standard Log Fields

```json
{
  "timestamp": "2026-05-08T14:23:01Z",
  "level": "INFO",
  "service": "bme280",
  "event": "mqtt_publish",
  "message": "Published reading"
}
```

## Common Events

- `service_started`
- `config_loaded`
- `mqtt_connected`
- `mqtt_disconnected`
- `sensor_read`
- `mqtt_publish`
- `sensor_error`

## Log Viewing

```bash
journalctl -u bme280 -f
journalctl -u api -f
journalctl -u bme280 -n 100 --no-pager
```

---

# Security Model

This system is designed for a local, single-device deployment.

## MQTT Broker

Mosquitto listens only on localhost.

```conf
listener 1883 127.0.0.1
allow_anonymous true
```

This prevents remote network access while keeping configuration simple.

## REST API

The API requires an API key in the `X-API-Key` header.

## Secrets

Secrets are stored in:

```text
/etc/home-monitor.env
```

## Future Expansion

If the API is exposed externally, TLS and stronger authentication can be added without changing application code.

---

# Design Principles & Decisions

## Separate Process Per Sensor

Each sensor runs independently. A failure in one service does not affect others.

## MQTT as the Internal Bus

MQTT decouples producers and consumers and provides retained latest-state messages.

## REST as the Single External Interface

All external consumers interact only with the API.

## Synchronous Sensor Services

Blocking I/O is simpler and fully adequate for the expected workloads.

## Configuration Over Code

Operational values are defined in TOML and environment variables.

## systemd Over Docker

systemd is the simplest and most reliable way to supervise local hardware-access services.

## Fail Fast

Initialization failures cause immediate process exit, allowing systemd to restart the service.

---

# Future Extensibility

## Adding a New Sensor

1. Create `services/<sensor_name>/`.
2. Implement `main.py` and `sensor.py`.
3. Add `config.toml` and systemd unit.
4. Define a payload model in `common/models.py`.
5. Deploy.

No changes to MQTT subscription configuration are required.

---

## Historical Storage

A new subscriber service can write MQTT data to:

- InfluxDB
- TimescaleDB
- BigQuery

The existing services remain unchanged.

---

## Sensor Status Topics (Optional)

Services may publish Last Will and Testament messages to:

```text
home/status/{sensor_id}
```

Example:

```json
{
  "status": "offline"
}
```

---

## WebSocket Support

The API may add a `/ws` endpoint for live push updates.

---

## External Exposure

A reverse proxy such as nginx can provide:

- HTTPS
- Rate limiting
- Additional authentication

---

# Appendix: MQTT Topics

| Topic | Description |
|------|------|
| `home/sensors/climate/bme280` | Climate measurements |
| `home/sensors/air/scd40` | CO₂ measurements |
| `home/sensors/audio/inmp441` | Sound measurements |
| `home/status/{sensor_id}` | Optional online/offline status |

