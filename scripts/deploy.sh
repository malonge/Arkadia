#!/usr/bin/env bash
# deploy.sh — Arkadia service deployment and update
#
# Copies systemd unit files, reloads systemd, enables all services, and
# starts them in the correct dependency order.
#
# Must be run as root:  sudo bash scripts/deploy.sh
#
# Idempotent — safe to re-run after a code change.  Running it will restart
# all Arkadia services so the latest code is picked up.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEMD_DIR="/etc/systemd/system"
ENV_FILE="/etc/home-monitor.env"

# Ordered service list: mosquitto is a system service installed separately;
# sensor services and api are the Arkadia-managed units.
SENSOR_SERVICES=(bme280 scd40 sgp40 audio)
ALL_ARKADIA_SERVICES=(bme280 scd40 sgp40 audio api)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()  { echo "[deploy] $*"; }
warn()  { echo "[deploy] WARNING: $*" >&2; }
die()   { echo "[deploy] ERROR: $*" >&2; exit 1; }

require_root() {
    [[ "${EUID:-$(id -u)}" -eq 0 ]] || die "This script must be run as root (sudo bash scripts/deploy.sh)."
}

detect_service_user() {
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
        echo "${SUDO_USER}"
    else
        stat -c '%U' "${REPO_ROOT}"
    fi
}

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

preflight() {
    [[ -f "${ENV_FILE}" ]] || die \
        "${ENV_FILE} not found. Run scripts/setup.sh first."

    local root
    root="$(grep -E '^ARKADIA_ROOT=' "${ENV_FILE}" | cut -d= -f2- || true)"
    [[ -n "${root}" ]] || die \
        "ARKADIA_ROOT is not set in ${ENV_FILE}. Run scripts/setup.sh first."

    if grep -q "change-me-before-starting-api" "${ENV_FILE}"; then
        warn "MONITOR_API_KEY in ${ENV_FILE} is still the placeholder value."
        warn "Update it before exposing the API to any clients."
    fi
}

# ---------------------------------------------------------------------------
# Ensure each service has a virtualenv (creates one if missing).
# This makes deploy.sh safe to run after a new service is added without
# requiring a full setup.sh re-run.
# ---------------------------------------------------------------------------

ensure_virtualenvs() {
    local service_user="$1"
    local service

    for service in "${ALL_ARKADIA_SERVICES[@]}"; do
        local svc_dir="${REPO_ROOT}/services/${service}"
        local venv_dir="${svc_dir}/.venv"
        local req_file="${svc_dir}/requirements.txt"

        [[ -d "${svc_dir}" ]] || continue

        if [[ ! -d "${venv_dir}" ]]; then
            info "Creating missing virtualenv for ${service}..."
            python3 -m venv "${venv_dir}"
            "${venv_dir}/bin/pip" install --quiet -e "${REPO_ROOT}"
            if [[ -f "${req_file}" ]]; then
                "${venv_dir}/bin/pip" install --quiet -r "${req_file}"
            fi
            chown -R "${service_user}:${service_user}" "${venv_dir}"
            info "  ${service} virtualenv ready."
        fi
    done
}

# ---------------------------------------------------------------------------
# Install service unit files
# ---------------------------------------------------------------------------

install_units() {
    local service_user="$1"
    local service

    for service in "${ALL_ARKADIA_SERVICES[@]}"; do
        local src_file
        # Find the .service file for this service.
        src_file="$(find "${REPO_ROOT}/services/${service}" -maxdepth 1 -name "*.service" | head -1)"
        if [[ -z "${src_file}" ]]; then
            warn "No .service file found for ${service} — skipping."
            continue
        fi

        local dst_file="${SYSTEMD_DIR}/${service}.service"

        info "Installing ${src_file} → ${dst_file}..."
        install -m 644 "${src_file}" "${dst_file}"

        # Replace the placeholder 'pi' username with the actual service user.
        if grep -q "^User=pi$" "${dst_file}"; then
            info "  Replacing User=pi with User=${service_user}..."
            sed -i "s/^User=pi$/User=${service_user}/" "${dst_file}"
        fi
    done
}

# ---------------------------------------------------------------------------
# Enable services
# ---------------------------------------------------------------------------

enable_services() {
    local service
    info "Reloading systemd daemon..."
    systemctl daemon-reload

    for service in "${ALL_ARKADIA_SERVICES[@]}"; do
        if [[ -f "${SYSTEMD_DIR}/${service}.service" ]]; then
            info "Enabling ${service}.service..."
            systemctl enable "${service}"
        fi
    done
}

# ---------------------------------------------------------------------------
# Start services in dependency order
# ---------------------------------------------------------------------------

start_services() {
    # Mosquitto must be up first.
    info "Ensuring mosquitto.service is running..."
    systemctl restart mosquitto
    sleep 1
    if ! systemctl is-active --quiet mosquitto; then
        die "mosquitto.service failed to start. Check: journalctl -u mosquitto -n 50"
    fi

    # Sensor services can start in parallel.
    info "Starting sensor services (bme280, scd40, sgp40, audio)..."
    local service
    for service in "${SENSOR_SERVICES[@]}"; do
        if [[ -f "${SYSTEMD_DIR}/${service}.service" ]]; then
            systemctl restart "${service}" || warn "${service}.service failed to restart — check logs."
        fi
    done

    # API depends on the broker being up (already confirmed above).
    info "Starting api.service..."
    systemctl restart api || warn "api.service failed to restart — check logs."

    # Brief pause so units have time to transition to active/failed.
    sleep 2
}

# ---------------------------------------------------------------------------
# Status report
# ---------------------------------------------------------------------------

print_status() {
    info ""
    info "Service status:"
    local service
    for service in mosquitto "${ALL_ARKADIA_SERVICES[@]}"; do
        local status
        status="$(systemctl is-active "${service}" 2>/dev/null || true)"
        printf "  %-12s %s\n" "${service}" "${status}"
    done
    info ""
    info "View logs with:  journalctl -u <service> -f"
    info "Full status  :   systemctl status bme280 scd40 sgp40 audio api"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

require_root
SERVICE_USER="$(detect_service_user)"
info "Repository root : ${REPO_ROOT}"
info "Service user    : ${SERVICE_USER}"

preflight
ensure_virtualenvs "${SERVICE_USER}"
install_units "${SERVICE_USER}"
enable_services
start_services
print_status

info "Deploy complete."
