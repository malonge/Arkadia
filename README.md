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
├── common/                    # Shared library (config, models, MQTT, I2C)
├── services/
│   ├── bme280/
│   │   ├── sensor.py          # BME280 driver (wraps adafruit-circuitpython-bme280)
│   │   ├── main.py            # Polling loop + MQTT publish
│   │   ├── config.toml        # Sensor and MQTT settings
│   │   ├── bme280.service     # systemd unit file
│   │   └── requirements.txt
│   ├── scd40/                 # CO₂ service (pending)
│   ├── audio/                 # Ambient sound service (pending)
│   └── api/                   # REST API service (pending)
├── config/
│   └── global.toml            # Shared broker and logging defaults
├── mosquitto/
│   └── mosquitto.conf         # Broker configuration
├── scripts/
│   ├── setup.sh               # First-time system setup
│   └── deploy.sh              # Service deployment / restart (pending)
├── tests/                     # Unit tests (no hardware required)
└── pyproject.toml
```

---

## Development Quick Start

These steps are for running the unit tests on any machine (no hardware required).

Pi OS Bookworm (and any modern Debian/Ubuntu) enforces [PEP 668](https://peps.python.org/pep-0668/) — you cannot install packages into the system Python directly. Always use a virtual environment.

```bash
# Create and activate a virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Install the common library in editable mode
pip install -e .

# Run the tests
pip install pytest
pytest
```

---

## Deploying on Raspberry Pi

### 1. Enable I2C

```bash
sudo raspi-config
# → Interface Options → I2C → Enable
# Reboot after enabling.
```

Or add the line directly and reboot:

```bash
echo "dtparam=i2c_arm=on" | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

Verify I2C is up and your sensor is visible:

```bash
sudo apt-get install -y i2c-tools
i2cdetect -y 1
```

You should see `76` or `77` in the grid output:

```
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- -- --
...
70: -- -- -- -- -- -- 76 --
```

If your sensor appears at `77` (SDO pin pulled high), edit `services/bme280/config.toml` and change `i2c_address = 0x76` to `i2c_address = 0x77` before continuing.

### 2. Install system packages

```bash
sudo bash scripts/setup.sh
```

This installs Mosquitto and applies `mosquitto/mosquitto.conf`.

### 3. Create the environment file

All services read `/etc/home-monitor.env` for the repository root path and any secrets.  Create it before enabling any service:

```bash
sudo tee /etc/home-monitor.env > /dev/null << EOF
# Absolute path to the Arkadia repository on this machine.
ARKADIA_ROOT=/home/$(whoami)/Projects/Arkadia
EOF
```

Adjust the path to match where you cloned the repo.

### 4. Set up the BME280 service virtualenv

```bash
cd services/bme280

# Create a virtualenv dedicated to this service
python3 -m venv .venv

# Install the common library from the repo
.venv/bin/pip install -e ../..

# Install the sensor driver and hardware abstraction layer
.venv/bin/pip install -r requirements.txt
```

### 5. Test the service manually before enabling systemd

```bash
# Make sure Mosquitto is running
sudo systemctl start mosquitto

# Run the service in the foreground — you should see JSON log lines
# and retained MQTT messages after ~35 s (5 samples × 0.5 s + 30 s sleep)
.venv/bin/python main.py
```

In another terminal, subscribe to verify the payload arrives:

```bash
mosquitto_sub -h 127.0.0.1 -t 'home/sensors/climate/bme280' -v
```

Press Ctrl-C to stop the service once you have confirmed it is working.

### 6. Install and enable the systemd service

```bash
# Install the service file
sudo cp services/bme280/bme280.service /etc/systemd/system/

# Change the User= field in the installed copy to your actual username
sudo sed -i "s/^User=pi$/User=$(whoami)/" /etc/systemd/system/bme280.service

# Confirm it looks right
grep "^User=" /etc/systemd/system/bme280.service

# Reload systemd and enable
sudo systemctl daemon-reload
sudo systemctl enable bme280
sudo systemctl start bme280
```

> **Note for Pi 5 / adafruit-blinka:** `lgpio` (the GPIO backend) creates
> temporary notification files in the service's working directory.
> `bme280.service` already sets `RuntimeDirectory=bme280` and
> `WorkingDirectory=/run/bme280` to give it a writable location.  If you
> ever need to re-apply this fix to an already-installed service file (e.g.
> after installing from an older commit), use a drop-in override:
> ```bash
> sudo mkdir -p /etc/systemd/system/bme280.service.d
> sudo tee /etc/systemd/system/bme280.service.d/workdir.conf > /dev/null << 'EOF'
> [Service]
> RuntimeDirectory=bme280
> WorkingDirectory=/run/bme280
> EOF
> sudo systemctl daemon-reload
> ```

### 7. Verify

```bash
# Check service status
sudo systemctl status bme280

# Watch structured JSON logs
journalctl -u bme280 -f

# Watch the MQTT topic
mosquitto_sub -h 127.0.0.1 -t 'home/sensors/climate/bme280' -v
```

---

## Sensors

| Sensor  | Interface | Topic                         | Measurements                        |
|---------|-----------|-------------------------------|-------------------------------------|
| BME280  | I2C       | `home/sensors/climate/bme280` | Temperature, humidity, pressure     |
| SCD40   | I2C       | `home/sensors/air/scd40`      | CO₂                                 |
| INMP441 | I2S       | `home/sensors/audio/inmp441`  | Ambient sound (RMS / dBFS)          |

---

## Mosquitto smoke test

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
- Paths and secrets: `/etc/home-monitor.env`

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
