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

**Responsibility:** Measure ambient sound level and publish both a periodic summary and a continuous real-time stream suitable for equalizer and waveform visualization.

- Interface: I2S
- Library: `sounddevice`
- Additional dependency: `numpy` (FFT computation)

The service operates two concurrent publish modes:

### Summary Mode (periodic, retained)

| Property | Value |
|------|------|
| Topic | `home/sensors/audio/inmp441` |
| Interval | 5 seconds |
| QoS | 1 |
| Retain | `true` |
| Aggregation | RMS over the full 5-second window |
| Payload | `AudioPayload` (`rms_amplitude`, `db_level`) |

### Stream Mode (continuous, non-retained)

| Property | Value |
|------|------|
| Topic | `home/sensors/audio/inmp441/stream` |
| Frame rate | 20 Hz (one message every 50 ms) |
| QoS | 0 |
| Retain | `false` |
| Aggregation | Per-frame FFT with Hann window |
| Payload | `AudioStreamPayload` (waveform, FFT bins, EQ bands, RMS) |

**Why QoS 0 for the stream?**  Dropping an occasional frame is acceptable for real-time visualization — the next frame arrives within 50 ms.  The lower overhead keeps end-to-end latency predictable.

**Why `retain=false` for the stream?**  Retained messages are replayed to every new subscriber.  A stale audio frame from minutes ago would mislead visualizations before live frames begin arriving.

### Frame Parameters

| Parameter | Default | Description |
|------|------|------|
| `sample_rate_hz` | 16 000 | I2S capture rate |
| `window_size` | 1 024 | Samples per frame (~64 ms of audio) |
| `fft_size` | 1 024 | FFT length; bins span 0–8 000 Hz in ~15.6 Hz steps |
| `eq_bands_hz` | `[63, 125, 250, 500, 1000, 2000, 4000, 8000]` | ISO 266 octave centres |
| `window_function` | `hann` | Applied before FFT to reduce spectral leakage |

### Polling Loop (Stream Mode)

```text
initialize sounddevice input stream (sample_rate_hz, blocksize=window_size)
loop forever:
    capture window_size samples → waveform (normalised float32)
    apply Hann window
    compute FFT → N/2 complex bins
    convert to magnitudes in dBFS
    aggregate bins into octave EQ bands
    compute RMS and dBFS of waveform
    publish AudioStreamPayload to …/stream (QoS 0, retain=false)
    [every 5 s: publish AudioPayload summary (QoS 1, retain=true)]
```

---

## API Service

**Responsibility:** Subscribe to sensor topics, expose the latest readings over HTTP, and bridge the real-time audio stream to WebSocket clients.

- Framework: FastAPI
- Port: 8000
- MQTT Subscriptions: `home/sensors/#` (summary + stream topics)

### Internal Components

- MQTT client
- Thread-safe in-memory state store
- HTTP routes
- WebSocket manager (for real-time audio stream)

### State Store

The state store is a dictionary keyed by `sensor_id`, protected by a `threading.Lock`.  Only summary payloads (from retained topics) are written into the store; `AudioStreamPayload` frames bypass the store and are forwarded directly to WebSocket connections.

### Startup Behavior

When the API service connects to MQTT, the broker immediately delivers retained sensor messages. The API therefore reconstructs its state immediately after startup.

### WebSocket Manager

A lightweight in-process broadcaster holds a set of active WebSocket connections.  When an `AudioStreamPayload` arrives on `home/sensors/audio/inmp441/stream`, the broadcaster serializes it and sends it to every connected client in the calling thread.  Slow or disconnected clients are removed from the set without blocking the MQTT callback.

---

# Data Models & MQTT Schema

All MQTT payloads are JSON and validated using shared Pydantic models.

## Topic Structure

```text
home/sensors/{category}/{sensor_id}           ← periodic summary (QoS 1, retain=true)
home/sensors/{category}/{sensor_id}/stream    ← real-time stream  (QoS 0, retain=false)
```

Examples:

- `home/sensors/climate/bme280`
- `home/sensors/air/scd40`
- `home/sensors/audio/inmp441`
- `home/sensors/audio/inmp441/stream`

The `/stream` sub-topic is currently defined only for the audio service.

## Publish Semantics

### Summary topics

Periodic summary messages are published with:

- QoS: `1`
- Retain: `true`

This ensures the latest reading is persisted by the broker and delivered to subscribers on connection.

### Stream topic (`…/stream`)

Real-time stream frames are published with:

- QoS: `0`
- Retain: `false`

QoS 0 reduces per-message overhead; losing an occasional frame is acceptable
for continuous visualization.  `retain=false` ensures new subscribers receive
only live frames, not a potentially minutes-old snapshot.

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

## Audio Stream Payload (`AudioStreamPayload`)

Published to `home/sensors/audio/inmp441/stream` at 20 Hz.

### Example

```json
{
  "schema_version": 1,
  "sensor_id": "inmp441",
  "timestamp": "2026-05-08T14:23:01.050Z",
  "readings": {
    "sample_rate_hz": 16000,
    "window_size": 1024,
    "waveform": [0.002, -0.005, 0.011, "...1024 values total..."],
    "fft_bins": {
      "frequencies_hz": [0.0, 15.625, 31.25, "...512 values total..."],
      "magnitudes_db": [-80.1, -62.4, -55.0, "...512 values total..."]
    },
    "eq_bands": {
      "bands_hz": [63, 125, 250, 500, 1000, 2000, 4000, 8000],
      "levels_db": [-42.1, -38.5, -35.2, -30.1, -28.7, -33.4, -40.0, -55.2]
    },
    "rms_amplitude": 0.018,
    "db_level": -34.9
  },
  "meta": {
    "sample_count": 1024,
    "aggregation": "fft",
    "window_function": "hann"
  },
  "diagnostics": {
    "uptime_seconds": 12345,
    "read_failures": 0
  }
}
```

### `readings` Fields

| Field | Type | Description |
|------|------|------|
| `sample_rate_hz` | `int` | Audio capture sample rate in Hz |
| `window_size` | `int` | Samples per frame |
| `waveform` | `float[]` | Time-domain samples, normalised to `[-1.0, 1.0]`; length = `window_size` |
| `fft_bins.frequencies_hz` | `float[]` | Bin centre frequencies from 0 Hz to Nyquist; length = `window_size / 2` |
| `fft_bins.magnitudes_db` | `float[]` | Bin magnitude in dBFS; same length as `frequencies_hz` |
| `eq_bands.bands_hz` | `float[]` | ISO 266 octave-band centre frequencies |
| `eq_bands.levels_db` | `float[]` | Mean power per band in dBFS |
| `rms_amplitude` | `float` | RMS of `waveform`, normalised to `[0, 1]` |
| `db_level` | `float` | RMS level in dBFS |

### `meta` Fields (stream)

| Field | Type | Description |
|------|------|------|
| `sample_count` | `int` | Equals `window_size` |
| `aggregation` | `str` | Always `"fft"` |
| `window_function` | `str` | Windowing function applied before FFT (default `"hann"`) |

### Visualization Mapping

| Visualization | Source fields |
|------|------|
| Oscilloscope / waveform (time × amplitude) | `readings.waveform`, x-axis derived from `sample_rate_hz` and `window_size` |
| Frequency spectrum (Hz × dBFS) | `readings.fft_bins.frequencies_hz` × `readings.fft_bins.magnitudes_db` |
| Equalizer bars (band × dBFS) | `readings.eq_bands.bands_hz` × `readings.eq_bands.levels_db` |

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

### `GET /ws/audio/stream` *(WebSocket)*

Streams real-time `AudioStreamPayload` frames to connected WebSocket clients.

The API service subscribes to `home/sensors/audio/inmp441/stream` (QoS 0) and
forwards each MQTT message as a UTF-8 JSON text frame to all active WebSocket
connections.  No buffering is performed; clients receive only frames that
arrive while they are connected.

**Protocol:** WebSocket (`ws://`)  
**Authentication:** API key supplied as a query parameter:
`ws://<pi-hostname>:8000/ws/audio/stream?api_key=<key>`  
**Frame format:** UTF-8 JSON text — one `AudioStreamPayload` per frame  
**Expected rate:** 20 Hz (one frame every ~50 ms)

```text
Client                            API service                MQTT broker
  │                                    │                          │
  │── WS upgrade ──────────────────►  │                          │
  │◄─ 101 Switching Protocols ──────  │                          │
  │                                    │◄── MQTT publish ─────── │
  │◄── JSON text frame ────────────── │  (inmp441/stream)        │
  │◄── JSON text frame ────────────── │                          │
  │   (repeats at 20 Hz)              │                          │
  │── close ───────────────────────►  │                          │
```

This endpoint is the recommended integration point for browser-based
equalizer and waveform visualizations.

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

Key models:

| Model | Description |
|------|------|
| `Meta` | Standard aggregation metadata |
| `StreamMeta` | Extends `Meta` with `window_function` for audio stream frames |
| `AudioReadings` | Summary audio readings (RMS, dBFS) |
| `FftBins` | FFT frequency bins (frequencies + magnitudes) |
| `EqBands` | Octave-band levels for equalizer display |
| `AudioStreamReadings` | Complete real-time frame (waveform + FFT + EQ bands + RMS) |
| `AudioPayload` | Typed envelope for the summary topic |
| `AudioStreamPayload` | Typed envelope for the real-time stream topic |

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

| Topic | QoS | Retain | Description |
|------|------|------|------|
| `home/sensors/climate/bme280` | 1 | `true` | Climate measurements (temperature, humidity, pressure) |
| `home/sensors/air/scd40` | 1 | `true` | CO₂ measurements |
| `home/sensors/audio/inmp441` | 1 | `true` | Audio summary (RMS amplitude, dBFS level) — 5 s interval |
| `home/sensors/audio/inmp441/stream` | 0 | `false` | Real-time audio frames (waveform, FFT bins, EQ bands) — 20 Hz |
| `home/status/{sensor_id}` | 1 | `true` | Optional online/offline LWT status |

