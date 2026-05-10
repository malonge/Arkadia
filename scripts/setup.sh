#!/usr/bin/env bash
# setup.sh — Arkadia first-time system setup (partial: Mosquitto only)
#
# This is the partial version delivered in PR 2.  The complete script
# (Python virtualenvs, I2C/I2S enablement, env file scaffold) is in PR 7.
#
# Must be run as root:  sudo bash scripts/setup.sh
#
# Idempotent — safe to re-run after a config change.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF_SRC="${REPO_ROOT}/mosquitto/mosquitto.conf"
CONF_DST="/etc/mosquitto/conf.d/arkadia.conf"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()  { echo "[setup] $*"; }
die()   { echo "[setup] ERROR: $*" >&2; exit 1; }

require_root() {
    [[ "${EUID:-$(id -u)}" -eq 0 ]] || die "This script must be run as root."
}

# ---------------------------------------------------------------------------
# Install Mosquitto
# ---------------------------------------------------------------------------

install_mosquitto() {
    info "Updating package lists..."
    apt-get update -qq

    info "Installing mosquitto and mosquitto-clients..."
    apt-get install -y -qq mosquitto mosquitto-clients
}

# ---------------------------------------------------------------------------
# Install configuration
# ---------------------------------------------------------------------------

install_config() {
    if [[ ! -f "${CONF_SRC}" ]]; then
        die "mosquitto/mosquitto.conf not found at ${CONF_SRC}"
    fi

    info "Installing ${CONF_SRC} → ${CONF_DST}..."
    install -m 644 "${CONF_SRC}" "${CONF_DST}"
}

# ---------------------------------------------------------------------------
# Enable and start service
# ---------------------------------------------------------------------------

enable_service() {
    info "Enabling mosquitto.service..."
    systemctl enable mosquitto

    info "Restarting mosquitto.service..."
    systemctl restart mosquitto

    # Give the broker a moment to come up before reporting status.
    sleep 1
    systemctl is-active --quiet mosquitto \
        && info "mosquitto.service is active." \
        || die "mosquitto.service failed to start. Check: journalctl -u mosquitto -n 50"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

require_root
install_mosquitto
install_config
enable_service

info "Done. Mosquitto is listening on 127.0.0.1:1883."
info "Verify with:"
info "  mosquitto_sub -h 127.0.0.1 -t 'test/#' &"
info "  mosquitto_pub -h 127.0.0.1 -t 'test/hello' -m 'world'"
