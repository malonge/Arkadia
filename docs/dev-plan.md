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

**Goal:** Third sensor service. Differs from I2C services in that it uses I2S and publishes two MQTT topics: a retained periodic summary and a non-retained real-time stream for equalizer and waveform visualization.

### Raspberry Pi 5 hardware requirements

The `googlevoicehat-soundcard` ALSA driver used on Pi 5 / Bookworm requires **48 000 Hz stereo** capture.  Configure `/boot/firmware/config.txt` and `/etc/asound.conf` as documented in `skills/pi-deployment.md` before deploying.

### Scope

- `services/audio/sensor.py`:
  - Opens an I2S input stream from the INMP441 via `sounddevice` at 48 000 Hz, 2 channels
  - Captures frames of `window_size` (default 2 400) samples; extracts the mono channel from stereo
  - Applies a Hann window and computes a 2 400-point FFT via `numpy.fft.rfft`
  - Converts FFT output to dBFS magnitudes: `20 * log10(|X[k]| / (window_size / 2))`
  - Aggregates FFT bins into ISO 266 octave bands (63, 125, 250, 500, 1000, 2000, 4000, 8000 Hz)
  - Computes per-frame RMS and dBFS
  - Returns both an `AudioStreamReadings` object (for the stream) and accumulated data (for the periodic summary)
- `services/audio/main.py`:
  - Initialises `sounddevice` input stream and MQTT client
  - **Stream loop** (20 Hz): publishes `AudioStreamPayload` to `home/sensors/audio/inmp441/stream` with QoS 0, `retain=false`
  - **Summary loop** (every 5 s): computes energy-average RMS over accumulated frames, publishes `AudioPayload` to `home/sensors/audio/inmp441` with QoS 1, `retain=true`
- `services/audio/config.toml`:
  ```toml
  [sensor]
  device = 0                # PortAudio device index — find with `python -m sounddevice`
  sample_rate_hz = 48000    # googlevoicehat-soundcard hardware requirement
  channels = 2              # driver always presents stereo
  channel = 0               # 0=left (L/R=GND), 1=right (L/R=3V3)
  window_size = 2400        # 50 ms at 48 kHz → 20 Hz frame rate
  window_function = "hann"
  eq_bands_hz = [63, 125, 250, 500, 1000, 2000, 4000, 8000]
  summary_interval_seconds = 5

  [mqtt]
  stream_topic  = "home/sensors/audio/inmp441/stream"
  summary_topic = "home/sensors/audio/inmp441"
  client_id     = "audio-service"
  ```
- `services/audio/audio.service` — `Group=audio` for ALSA/sounddevice access; `User=<username>` must match the actual Pi user
- `services/audio/requirements.txt` — `sounddevice`, `numpy`

### Acceptance Criteria

- Service starts and publishes retained JSON to `home/sensors/audio/inmp441` every 5 seconds.
- Service publishes non-retained JSON to `home/sensors/audio/inmp441/stream` at approximately 20 Hz.
- Both payloads validate against the corresponding `common` Pydantic models (`AudioPayload`, `AudioStreamPayload`).
- `fft_bins.frequencies_hz` has `window_size / 2 + 1` entries spanning 0 Hz to `sample_rate_hz / 2`.
- `eq_bands.levels_db` has one entry per configured `eq_bands_hz` centre.
- `waveform` has exactly `window_size` entries, all in `[-1.0, 1.0]`.
- RMS value in the summary payload is non-zero under ambient sound conditions.

---

## PR 6 — API Service

**Goal:** The API service — MQTT subscriber, in-memory state store, HTTP layer, and WebSocket bridge for the real-time audio stream.

### Scope

- `services/api/store.py` — thread-safe dict protected by `threading.Lock`, keyed by `sensor_id`, stores latest deserialized payload and receipt timestamp; `AudioStreamPayload` frames are **not** stored — they are forwarded directly to the WebSocket manager
- `services/api/ws.py` — `AudioStreamBroadcaster`: holds a set of active `WebSocket` connections; `broadcast(data: str)` sends to all connections and drops any that are closed or errored
- `services/api/main.py` — FastAPI app init; starts MQTT client with wildcard subscription `home/sensors/#` in a background thread via `loop_start()`; on message: if topic ends in `/stream`, call `AudioStreamBroadcaster.broadcast()`; otherwise deserialize, validate, upsert store
- `services/api/routes/health.py` — `GET /health`: broker connectivity status and uptime
- `services/api/routes/version.py` — `GET /version`: service name, version string, git commit
- `services/api/routes/sensors.py`:
  - `GET /sensors` — latest reading from all sensors
  - `GET /sensors/{sensor_id}` — latest reading for one sensor (200 / 404 / 503)
  - `GET /sensors/{sensor_id}/status` — staleness metadata
- `services/api/routes/audio.py`:
  - `GET /ws/audio/stream` (WebSocket) — upgrades connection, registers with `AudioStreamBroadcaster`, sends frames until client disconnects; requires `api_key` query parameter
- API key middleware — validates `X-API-Key` header on HTTP routes except `/health`; WebSocket route validates `api_key` query parameter on upgrade
- `services/api/config.toml`, `services/api/api.service`, `services/api/requirements.txt`

### Acceptance Criteria

- API starts and immediately hydrates state from retained MQTT messages.
- All HTTP endpoints return correct responses and shapes.
- Returns `401` on missing or incorrect API key.
- Returns `503` on a known sensor ID with no data received yet.
- Staleness flag flips correctly when a sensor stops publishing.
- WebSocket endpoint at `GET /ws/audio/stream` receives `AudioStreamPayload` JSON frames at approximately 20 Hz while the audio service is running.
- Connecting a second WebSocket client causes both clients to receive frames simultaneously.
- Closing a WebSocket connection does not affect other active connections.

---

## PR 7 — `setup.sh` & `deploy.sh`

**Goal:** Fully automated setup and deploy scripts. The single-command story for getting a fresh Pi running.

### Scope

- `scripts/setup.sh` (complete):
  - apt installs (`mosquitto`, `python3-venv`, I2C tools)
  - Enable I2C and I2S in `/boot/firmware/config.txt`
  - Create a virtualenv per service
  - `pip install -e .` (from repo root) in each service virtualenv to install the `common` package
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
