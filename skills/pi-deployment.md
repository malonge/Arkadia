# Skill: Raspberry Pi Deployment

**Use this skill whenever:** deploying or updating any Arkadia service on the
Raspberry Pi, debugging a failing systemd unit, or configuring hardware
(I2C, I2S, audio).

---

## Target hardware

| Property | Value |
|----------|-------|
| Board | Raspberry Pi 5 |
| OS | Raspberry Pi OS Debian Bookworm (64-bit) |
| Username | `micheldelving` (not `pi`) |
| Repo path | `/home/micheldelving/Projects/Arkadia` |
| Access | SSH |

---

## Critical gotchas — read first

### 1. Username is `micheldelving`, not `pi`

Every `.service` file in this repo ships with `User=pi`.  This **must** be
changed to `User=micheldelving` before or immediately after copying to
`/etc/systemd/system/`.  Forgetting this produces `status=217/USER` and the
service loops in rapid-restart until the rate-limit kicks in.

### 2. `pip install -e` must target the repo root, not `common/`

`pyproject.toml` lives at the **repo root**, not inside `common/`.  Always
install the common package with:

```bash
services/<name>/.venv/bin/pip install -e .       # run from repo root
```

Not:

```bash
services/<name>/.venv/bin/pip install -e ./common  # ✗ fails
```

### 3. sounddevice requires a device index, not an ALSA string

`sounddevice` / PortAudio does **not** accept raw ALSA device strings such
as `hw:0,0`, `plughw:0,0`, or `mic_sv`.  Always pass either:

- an **integer** device index from `python -m sounddevice`, or
- a **substring** of the device name as shown in that listing.

---

## Standard service deployment procedure

```bash
# 1. Pull latest code
cd /home/micheldelving/Projects/Arkadia
git pull origin <branch>

# 2. Create virtualenv and install dependencies
python3 -m venv services/<name>/.venv
services/<name>/.venv/bin/pip install -e .
services/<name>/.venv/bin/pip install -r services/<name>/requirements.txt

# 3. Ensure /etc/home-monitor.env exists
#    Must contain ARKADIA_ROOT pointing to the repo.
cat /etc/home-monitor.env
# Expected: ARKADIA_ROOT=/home/micheldelving/Projects/Arkadia
# Create if missing:
echo "ARKADIA_ROOT=/home/micheldelving/Projects/Arkadia" | sudo tee /etc/home-monitor.env

# 4. Fix username in the service file, then install it
#    Open the unit file and confirm User=micheldelving (not User=pi).
sudo cp services/<name>/<name>.service /etc/systemd/system/
sudo nano /etc/systemd/system/<name>.service   # verify User= line
sudo systemctl daemon-reload
sudo systemctl enable <name>
sudo systemctl start <name>

# 5. Verify
systemctl status <name>
journalctl -u <name> -f
```

---

## Audio service (INMP441 I2S microphone)

### I2S kernel setup (one-time, requires reboot)

Add to `/boot/firmware/config.txt`:

```
dtparam=i2s=on
dtoverlay=googlevoicehat-soundcard
dtparam=audio=on
```

Find the existing `dtoverlay=vc4-kms-v3d` line and add `,noaudio` to prevent
HDMI from claiming card 0:

```
dtoverlay=vc4-kms-v3d,noaudio
```

Reboot, then verify with `arecord -l` — should show
`card 0: sndrpigooglevoi [snd_rpi_googlevoicehat_soundcar]`.

### ALSA softvol layer (`/etc/asound.conf`)

Create this file to add software gain control:

```
pcm.mic_hw {
    type hw
    card 0
    device 0
    channels 2
    format S32_LE
    rate 48000
}

pcm.mic_sv {
    type softvol
    slave { pcm "mic_hw" }
    control {
        name "Mic Capture Volume"
        card 0
    }
    min_dB -3.0
    max_dB 20.0
    resolution 256
}

pcm.!default {
    type asym
    playback.pcm "default"
    capture.pcm "mic_sv"
}
```

### Finding the sounddevice device index

```bash
services/audio/.venv/bin/python -m sounddevice
```

On this Pi the INMP441 appears as:

```
0 snd_rpi_googlevoicehat_soundcar: Google voiceHAT SoundCard HiFi voicehat-hifi-0 (hw:0,0), ALSA (2 in, 2 out)
```

Use `device = 0` in `services/audio/config.toml`.

### Working audio hardware parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| `device` | `0` | Integer index, not a string |
| `sample_rate_hz` | `48000` | Hardware requirement — 16 000 Hz is not supported |
| `channels` | `2` | Driver always presents stereo |
| `channel` | `0` | Left channel for L/R=GND; use `1` for L/R=3V3 |
| `window_size` | `2400` | 50 ms at 48 kHz = 20 Hz frame rate |
| `window_function` | `"hann"` | |

### Set microphone gain

```bash
amixer -D hw:0 sset 'Mic' 10dB
```

This resets on reboot.  Add this line before starting the service in any
startup script, or store with `sudo alsactl store` (though ALSA state restore
is unreliable on Bookworm — see tech-design.md).

### Expected log output when working

```
audio_stream_opened  — Audio stream opened (device=0, rate=48000 Hz, channels=2, window=2400 samples)
poll_loop_start      — Entering stream loop (window=2400 samples, interval=5s)
mqtt_publish         — Summary: rms=0.00xx dBFS=-5x.x (frames=100, failures=0)
```

100 frames per 5-second summary window confirms the 20 Hz frame rate.

---

## SGP40 VOC sensor

The SGP40 communicates over I2C at address `0x59`.  No kernel overlays or
special configuration are required beyond I2C being enabled.

### Expected log output when working

```
i2c_bus_open    — SGP40 ready at I2C address 0x59 (bus 1)
status_online   — Published online status
poll_loop_start — Entering poll loop (sample_interval=1s, publish_interval=60s)
sensor_read     — VOC Index: 97 (failures: 0)
```

The VOC Index starts near 100 (algorithm baseline) and typically takes
5–10 minutes to settle after startup as the Sensirion exponential moving
average initialises.

### Verify the sensor is publishing

```bash
mosquitto_sub -h 127.0.0.1 -t 'home/sensors/air/sgp40' -v
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `status=217/USER` | `User=pi` in service file | Edit unit file, change to `User=micheldelving`, `daemon-reload` |
| `.venv/bin/python: No such file or directory` | Virtualenv never created | `python3 -m venv services/<name>/.venv && services/<name>/.venv/bin/pip install -e . && services/<name>/.venv/bin/pip install -r services/<name>/requirements.txt`; or re-run `sudo bash scripts/setup.sh` |
| `file:///…/common does not appear to be a Python project` | `pip install -e ./common` | Use `pip install -e .` from repo root |
| `No input device matching 'plughw:0,0'` | ALSA string passed to sounddevice | Use integer index from `python -m sounddevice` |
| `ALSA error -22 Invalid argument` | softvol/PortAudio incompatibility | Use hardware device index (`device = 0`) |
| `arecord -l` shows nothing | Missing dtoverlay or no reboot | Check `/boot/firmware/config.txt`, reboot |
| Very low RMS, flat waveform | Gain not set | `amixer -D hw:0 sset 'Mic' 10dB` |
| `Start request repeated too quickly` | Service hit restart rate-limit | `sudo systemctl reset-failed <name>` then `start` |
| SGP40 VOC Index stuck at 100 | Algorithm still warming up | Normal — allow 5–10 min; index stabilises once baseline is learned |

---

## Useful verification commands

```bash
# --- All services ---
systemctl status bme280 scd40 sgp40 audio api     # quick overview
journalctl -u <name> -n 50 --no-pager             # last 50 log lines
journalctl -u <name> -f                           # follow live logs
sudo systemctl reset-failed <name>                # clear restart rate-limit

# --- MQTT ---
mosquitto_sub -h 127.0.0.1 -t 'home/sensors/#' -v          # all sensor readings
mosquitto_sub -h 127.0.0.1 -t 'home/status/#' -v           # online/offline status
mosquitto_sub -h 127.0.0.1 -t 'home/sensors/air/sgp40' -v  # SGP40 VOC only
mosquitto_sub -h 127.0.0.1 -t 'home/sensors/audio/#' -v    # audio topics

# --- Audio hardware ---
arecord -l                                        # list ALSA capture devices
arecord -D hw:0,0 --dump-hw-params                # show hardware constraints
services/audio/.venv/bin/python -m sounddevice    # list PortAudio devices
amixer -D hw:0                                    # show current mixer controls
amixer -D hw:0 sset 'Mic' 10dB                   # set capture gain

# --- I2C (BME280, SCD40, SGP40) ---
i2cdetect -y 1                                    # scan bus 1 — should show 0x59, 0x62, 0x76/0x77
```
