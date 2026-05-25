#!/usr/bin/env bash
# setup.sh — Arkadia first-time system setup
#
# Installs system packages, configures I2C/I2S hardware, creates per-service
# Python virtualenvs, and scaffolds /etc/home-monitor.env.
#
# Must be run as root:  sudo bash scripts/setup.sh
#
# Idempotent — safe to re-run after a code or configuration change.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()  { echo "[setup] $*"; }
warn()  { echo "[setup] WARNING: $*" >&2; }
die()   { echo "[setup] ERROR: $*" >&2; exit 1; }

require_root() {
    [[ "${EUID:-$(id -u)}" -eq 0 ]] || die "This script must be run as root (sudo bash scripts/setup.sh)."
}

# Return the user who invoked sudo, falling back to the owner of REPO_ROOT.
detect_service_user() {
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
        echo "${SUDO_USER}"
    else
        stat -c '%U' "${REPO_ROOT}"
    fi
}

# Add a line to a file only if it is not already present.
append_if_missing() {
    local file="$1" line="$2"
    if ! grep -qF "${line}" "${file}" 2>/dev/null; then
        echo "${line}" >> "${file}"
        info "  Added: ${line}"
    else
        info "  Already present: ${line}"
    fi
}

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------

install_packages() {
    info "Updating package lists..."
    apt-get update -qq

    info "Installing system packages..."
    apt-get install -y -qq \
        mosquitto \
        mosquitto-clients \
        python3-venv \
        python3-dev \
        i2c-tools \
        libasound2-dev
}

# ---------------------------------------------------------------------------
# 2. Mosquitto configuration
# ---------------------------------------------------------------------------

install_mosquitto_config() {
    local src="${REPO_ROOT}/mosquitto/mosquitto.conf"
    local dst="/etc/mosquitto/conf.d/arkadia.conf"

    [[ -f "${src}" ]] || die "mosquitto/mosquitto.conf not found at ${src}"

    info "Installing Mosquitto config → ${dst}..."
    install -m 644 "${src}" "${dst}"

    info "Enabling and restarting mosquitto.service..."
    systemctl enable mosquitto
    systemctl restart mosquitto
    sleep 1
    if systemctl is-active --quiet mosquitto; then
        info "mosquitto.service is active."
    else
        die "mosquitto.service failed to start. Check: journalctl -u mosquitto -n 50"
    fi
}

# ---------------------------------------------------------------------------
# 3. I2C enablement
# ---------------------------------------------------------------------------

enable_i2c() {
    if command -v raspi-config &>/dev/null; then
        info "Enabling I2C via raspi-config..."
        raspi-config nonint do_i2c 0
    else
        warn "raspi-config not found — skipping I2C enablement (not on a Raspberry Pi?)."
    fi
}

# ---------------------------------------------------------------------------
# 4. I2S / audio hardware configuration
# ---------------------------------------------------------------------------

BOOT_CONFIG="/boot/firmware/config.txt"

enable_i2s() {
    if [[ ! -f "${BOOT_CONFIG}" ]]; then
        warn "${BOOT_CONFIG} not found — skipping I2S configuration (not on a Raspberry Pi?)."
        return
    fi

    info "Configuring I2S in ${BOOT_CONFIG}..."

    # Append vc4-kms-v3d,noaudio if the plain variant exists but noaudio is absent.
    if grep -q "dtoverlay=vc4-kms-v3d" "${BOOT_CONFIG}" && \
       ! grep -q "dtoverlay=vc4-kms-v3d,noaudio" "${BOOT_CONFIG}"; then
        info "  Patching vc4-kms-v3d → vc4-kms-v3d,noaudio..."
        sed -i 's/dtoverlay=vc4-kms-v3d$/dtoverlay=vc4-kms-v3d,noaudio/' "${BOOT_CONFIG}"
    else
        info "  vc4-kms-v3d,noaudio already configured."
    fi

    append_if_missing "${BOOT_CONFIG}" "dtparam=i2s=on"
    append_if_missing "${BOOT_CONFIG}" "dtoverlay=googlevoicehat-soundcard"
    append_if_missing "${BOOT_CONFIG}" "dtparam=audio=on"

    info "I2S configuration written.  A reboot is required for changes to take effect."
}

install_asound_conf() {
    local dst="/etc/asound.conf"
    if [[ -f "${dst}" ]]; then
        info "/etc/asound.conf already exists — leaving untouched."
        return
    fi

    info "Writing ALSA softvol layer to ${dst}..."
    cat > "${dst}" << 'EOF'
# Arkadia — ALSA configuration for INMP441 I2S microphone
# Provides a software volume control layer (mic_sv) over the raw hardware
# device (mic_hw).  The audio service uses device index 0 (the hw device)
# rather than the mic_sv named device because PortAudio/sounddevice cannot
# negotiate hardware parameters through the softvol layer.

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
EOF
}

# ---------------------------------------------------------------------------
# 5. Per-service Python virtualenvs
# ---------------------------------------------------------------------------

SERVICES=(bme280 scd40 audio api)

create_virtualenvs() {
    local service user="$1"
    for service in "${SERVICES[@]}"; do
        local svc_dir="${REPO_ROOT}/services/${service}"
        local venv_dir="${svc_dir}/.venv"
        local req_file="${svc_dir}/requirements.txt"

        if [[ ! -d "${svc_dir}" ]]; then
            warn "Service directory not found: ${svc_dir} — skipping."
            continue
        fi

        info "Setting up virtualenv for ${service}..."

        if [[ ! -d "${venv_dir}" ]]; then
            info "  Creating ${venv_dir}..."
            python3 -m venv "${venv_dir}"
        else
            info "  Virtualenv already exists at ${venv_dir}."
        fi

        info "  Installing common package (pip install -e .)..."
        "${venv_dir}/bin/pip" install --quiet -e "${REPO_ROOT}"

        if [[ -f "${req_file}" ]]; then
            info "  Installing ${service} requirements..."
            "${venv_dir}/bin/pip" install --quiet -r "${req_file}"
        fi

        # Ensure the virtualenv is owned by the service user, not root.
        chown -R "${user}:${user}" "${venv_dir}"
    done
}

# ---------------------------------------------------------------------------
# 6. /etc/home-monitor.env scaffold
# ---------------------------------------------------------------------------

ENV_FILE="/etc/home-monitor.env"
PLACEHOLDER_KEY="change-me-before-starting-api"

scaffold_env_file() {
    local repo_root="$1"

    if [[ -f "${ENV_FILE}" ]]; then
        # Update ARKADIA_ROOT if it differs (e.g. repo was moved).
        local current_root
        current_root="$(grep -E '^ARKADIA_ROOT=' "${ENV_FILE}" | cut -d= -f2- || true)"
        if [[ "${current_root}" != "${repo_root}" ]]; then
            info "Updating ARKADIA_ROOT in ${ENV_FILE}..."
            sed -i "s|^ARKADIA_ROOT=.*|ARKADIA_ROOT=${repo_root}|" "${ENV_FILE}"
        else
            info "${ENV_FILE} already exists with correct ARKADIA_ROOT."
        fi
        return
    fi

    info "Creating ${ENV_FILE}..."
    cat > "${ENV_FILE}" << EOF
# Arkadia environment file — loaded by all service units via EnvironmentFile=
# Set these values before starting services.

# Absolute path to the Arkadia repository on this machine.
ARKADIA_ROOT=${repo_root}

# API authentication key.  Change this to a strong random value before
# starting the api service.  Generate one with:
#   python3 -c "import secrets; print(secrets.token_hex(32))"
MONITOR_API_KEY=${PLACEHOLDER_KEY}
EOF
    chmod 640 "${ENV_FILE}"
    info "  Created ${ENV_FILE}."
    warn "  MONITOR_API_KEY is set to a placeholder — update it before starting the API."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

require_root
SERVICE_USER="$(detect_service_user)"
info "Repository root : ${REPO_ROOT}"
info "Service user    : ${SERVICE_USER}"

install_packages
install_mosquitto_config
enable_i2c
enable_i2s
install_asound_conf
create_virtualenvs "${SERVICE_USER}"
scaffold_env_file "${REPO_ROOT}"

info ""
info "Setup complete."
info ""
info "Next steps:"
info "  1. If I2S lines were added to ${BOOT_CONFIG}, reboot the Pi."
info "  2. Update MONITOR_API_KEY in ${ENV_FILE}."
info "  3. Run:  sudo bash scripts/deploy.sh"
