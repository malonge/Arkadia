# Arkadia — Agent Instructions

## Project Overview

Arkadia is a home environment monitoring system designed for Raspberry Pi 5. It reads sensor data (temperature, humidity, pressure, CO₂, sound), publishes to a local MQTT broker, and exposes readings via a REST API. See `docs/tech-design.md` for full architecture and `docs/dev-plan.md` for the PR-sequenced work breakdown.

## Cursor Cloud specific instructions

### Development environment

- **Python 3.12** is the runtime. The virtualenv lives at `/workspace/.venv`.
- Activate with: `source /workspace/.venv/bin/activate`
- Core dev dependencies pre-installed: `fastapi`, `uvicorn`, `pydantic`, `paho-mqtt`, `toml`, `pytest`, `ruff`.
- When source code is added (starting from PR 1), install the `common/` package with `pip install -e ./common` from the activated venv.

### Mosquitto MQTT broker

- Mosquitto is installed via apt (`mosquitto`, `mosquitto-clients`).
- It does **not** auto-start in the cloud VM (no systemd init). Start it manually:
  ```
  mosquitto -d -c /etc/mosquitto/mosquitto.conf
  ```
- Verify with: `mosquitto_pub -h localhost -t test -m hello` and `mosquitto_sub -h localhost -t test -v`.

### Lint and test

- **Lint:** `ruff check .` (from repo root, venv activated).
- **Tests:** `pytest` (from repo root, venv activated). No tests exist yet; they will be added starting with PR 1.

### Running the API service

- Once PR 6 (API service) is implemented, run with:
  ```
  cd services/api && python main.py
  ```
  or via uvicorn directly. The API listens on port 8000.
- The API requires the Mosquitto broker to be running first.

### Hardware dependencies

- Sensor services (BME280, SCD40, Audio) require Raspberry Pi hardware and cannot run in the cloud VM. Unit tests for `common/` and the API service should work without hardware.

---

## Skills

Skills are SOPs for specific tasks. Read the relevant skill file before performing the task it covers.

| Skill file | Use when |
|------------|----------|
| `skills/pi-deployment.md` | Deploying or updating any service on the Raspberry Pi, debugging a failing systemd unit, configuring I2C/I2S hardware, or troubleshooting the audio device |
