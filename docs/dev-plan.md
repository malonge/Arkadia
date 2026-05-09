# Home Environment Monitor — PR Breakdown

**Purpose:** Sequenced work breakdown for an AI coding agent.
Each PR is independently scoped and produces a verifiable outcome before the next begins.

---

## Sequencing Overview

```
PR 1 (common/)
    └── PR 2 (mosquitto)
            └── PR 3 (bme280)
            └── PR 4 (scd40)
            └── PR 5 (audio)
                    └── PR 6 (api)
                            └── PR 7 (deploy scripts)
                                    └── PR 8 (LWT — optional)
```

PRs 3, 4, and 5 can be worked in parallel once PR 2 is merged. PR 6 can start as soon as any one sensor service is producing messages — it does not need all three.

---

## PR 1 — Repo Scaffold & `common/` Library

**Goal:** Establish the monorepo skeleton and implement all shared code. Nothing runnable yet, but all subsequent PRs depend on this.

### Scope

- Initialize repo structure: `common/`, `services/`, `config/`, `scripts/`, `mosquitto/`
- `pyproject.toml` with `common` as an installable local package
- `config/global.toml` with broker and logging defaults
- `common/config.py` — TOML loader, global+local merge, typed config objects, fail-fast validation
- `common/models.py` — Pydantic models for all three sensor payloads plus the standard envelope (`schema_version`, `sensor_id`, `timestamp`, `readings`, `meta`, `diagnostics`)
- `common/mqtt.py` — `paho-mqtt` wrapper: `connect()`, `publish()`, `subscribe()`, auto-reconnect, `loop_start()`, structured logging
- `common/i2c.py` — I2C base class: bus init, address config, common error handling
- `README.md` skeleton

### Acceptance Criteria

- `pip install -e ./common` succeeds.
- All models importable.
- Unit tests pass for config loading and model validation (no hardware required).

---

## PR 2 — Mosquitto Setup & Configuration

**Goal:** Get the MQTT broker running and verified locally.

### Scope

- `mosquitto/mosquitto.conf` — listener bound to `127.0.0.1:1883`, `allow_anonymous true`, persistence enabled, log to journal
- `scripts/setup.sh` (partial) — installs `mosquitto` via apt, copies conf to `/etc/mosquitto/conf.d/`, enables and starts `mosquitto.service`
- Verify with `mosquitto_pub` / `mosquitto_sub` smoke test documented in README

### Acceptance Criteria

- Broker starts on boot.
- A test publish/subscribe round-trip works on localhost.
- Connection from outside localhost is refused.

---

## PR 3 — BME280 Sensor Service

**Goal:** First real sensor service, end-to-end from hardware to MQTT.

### Scope

- `services/bme280/sensor.py` — wraps `adafruit-circuitpython-bme280`, exposes a `read() -> dict` method
- `services/bme280/main.py` — polling loop: collect 5 samples, median aggregate, build payload using `common/models.py`, publish via `common/mqtt.py`, sleep
- `services/bme280/config.toml` — I2C bus, address, sample count, interval, topic, client ID, QoS, retain
- `services/bme280/bme280.service` — systemd unit with `After=mosquitto.service`, `Requires=mosquitto.service`, hardening directives (`NoNewPrivileges`, `PrivateTmp`, `ProtectSystem`), `EnvironmentFile`
- `services/bme280/requirements.txt` for the service virtualenv

### Acceptance Criteria

- Service starts and publishes retained JSON to `home/sensors/climate/bme280` on the configured interval.
- Service restarts cleanly on failure.
- Payload validates against the `common` Pydantic model.

---

## PR 4 — SCD40 Sensor Service

**Goal:** Second sensor service, following the identical pattern established in PR 3.

### Scope

- `services/scd40/sensor.py` — wraps `adafruit-circuitpython-scd4x`; note that the SCD40 has a fixed 5s internal measurement cycle and reads must be gated accordingly
- `services/scd40/main.py` — polling loop with median of 3 samples
- `services/scd40/config.toml`, `services/scd40/scd40.service`, `services/scd40/requirements.txt`

### Acceptance Criteria

- Service starts and publishes retained JSON to `home/sensors/air/scd40` on the configured interval.
- Payload validates against the `common` Pydantic model.

---

## PR 5 — Audio Service

**Goal:** Third sensor service. Differs from I2C services in that it uses I2S and RMS aggregation rather than median of discrete samples.

### Scope

- `services/audio/sensor.py` — reads I2S frames from the INMP441 via `sounddevice`, computes RMS amplitude and dB over the sample window
- `services/audio/main.py`, `services/audio/config.toml`, `services/audio/audio.service`, `services/audio/requirements.txt`

### Acceptance Criteria

- Service starts and publishes retained JSON to `home/sensors/audio/inmp441` on the configured interval.
- RMS value is non-zero under ambient sound conditions.
- Payload validates against the `common` Pydantic model.

---

## PR 6 — API Service

**Goal:** The API service — MQTT subscriber, in-memory state store, and HTTP layer.

### Scope

- `services/api/store.py` — thread-safe dict protected by `threading.Lock`, keyed by `sensor_id`, stores latest deserialized payload and receipt timestamp
- `services/api/main.py` — FastAPI app init; starts MQTT client with wildcard subscription `home/sensors/#` in a background thread via `loop_start()`; on message: deserialize, validate against `common` model, upsert store
- `services/api/routes/health.py` — `GET /health`: broker connectivity status and uptime
- `services/api/routes/version.py` — `GET /version`: service name, version string, git commit (read from environment or a `version.py` generated at deploy time)
- `services/api/routes/sensors.py`:
  - `GET /sensors` — latest reading from all sensors
  - `GET /sensors/{sensor_id}` — latest reading for one sensor (200 / 404 / 503)
  - `GET /sensors/{sensor_id}/status` — staleness metadata
- API key middleware — validates `X-API-Key` header on all routes except `/health`
- `services/api/config.toml`, `services/api/api.service`, `services/api/requirements.txt`

### Acceptance Criteria

- API starts and immediately hydrates state from retained MQTT messages.
- All endpoints return correct responses and shapes.
- Returns `401` on missing or incorrect API key.
- Returns `503` on a known sensor ID with no data received yet.
- Staleness flag flips correctly when a sensor stops publishing.

---

## PR 7 — `setup.sh` & `deploy.sh`

**Goal:** Fully automated setup and deploy scripts. The single-command story for getting a fresh Pi running.

### Scope

- `scripts/setup.sh` (complete):
  - apt installs (`mosquitto`, `python3-venv`, I2C tools)
  - Enable I2C and I2S in `/boot/firmware/config.txt`
  - Create a virtualenv per service
  - `pip install -e ../../common` in each service virtualenv
  - Copy `mosquitto/mosquitto.conf` to `/etc/mosquitto/conf.d/`
  - Scaffold `/etc/home-monitor.env` with placeholder values
- `scripts/deploy.sh`:
  - Copy all `.service` files to `/etc/systemd/system/`
  - `systemctl daemon-reload`
  - `systemctl enable` all services
  - `systemctl start` in dependency order: `mosquitto` → sensor services → `api`
  - Print status for all services on completion
- Both scripts must be idempotent — safe to re-run after a code change

### Acceptance Criteria

- Running `setup.sh` on a fresh Pi followed by `deploy.sh` brings all services up.
- `systemctl status` shows all services active.
- `journalctl` output shows structured JSON log lines from each service.
- Re-running `deploy.sh` after a code change restarts affected services without error.

---

## PR 8 — LWT & Sensor Status Topics *(optional)*

**Goal:** Add Last Will and Testament messages so the broker automatically publishes an offline status if a sensor service disconnects ungracefully.

### Scope

- Update `common/mqtt.py` to accept an optional LWT config and register it on `connect()`
- Each sensor service configures an LWT pointing to `home/status/{sensor_id}` with payload `{"status": "offline"}`
- Each sensor service publishes `{"status": "online"}` to `home/status/{sensor_id}` on successful startup
- Update `services/api/store.py` to track online/offline status per sensor from `home/status/#`
- Update `GET /sensors/{sensor_id}/status` to include a `connectivity` field: `"online"` / `"offline"` / `"unknown"`

### Acceptance Criteria

- Killing a sensor service process causes the broker to publish the offline LWT within one keepalive interval.
- Restarting the service causes an online message to be published.
- The API `/status` endpoint reflects connectivity state correctly.

---

## Reference: Design Document Decisions Carried Into This Breakdown

| Decision | Reflected In |
|----------|-------------|
| `retain=true` on all sensor publishes | PR 3, 4, 5 — config and payload publish call |
| Wildcard MQTT subscription `home/sensors/#` | PR 6 — API service config and subscription |
| `diagnostics` block in payloads | PR 1 — `common/models.py` |
| `GET /version` endpoint | PR 6 — `routes/version.py` |
| Mosquitto bound to `127.0.0.1` only | PR 2 — `mosquitto.conf` |
| systemd hardening directives | PR 3, 4, 5, 6 — all `.service` files |
| `event` field in structured logs | PR 1 — `common/mqtt.py` and logging setup |
| Secrets via `EnvironmentFile` only | PR 7 — `setup.sh` scaffolds `/etc/home-monitor.env` |
