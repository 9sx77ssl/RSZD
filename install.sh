#!/usr/bin/env bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
ENV_EXAMPLE="${SCRIPT_DIR}/.env.example"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

resolve_runtime_path() {
    local raw_path="$1"
    if [[ "${raw_path}" = /* ]]; then
        printf '%s\n' "${raw_path}"
    else
        printf '%s/%s\n' "${INSTALL_DIR}" "${raw_path}"
    fi
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        log_error "Run install.sh with sudo or as root."
        exit 1
    fi
}

ensure_supported_os() {
    if [[ ! -f /etc/os-release ]]; then
        log_error "Unsupported system: /etc/os-release not found."
        exit 1
    fi
    # shellcheck source=/dev/null
    source /etc/os-release
    case "${ID:-}" in
        ubuntu|debian)
            log_ok "Detected supported OS: ${PRETTY_NAME:-$ID}"
            ;;
        *)
            log_error "This installer officially supports Ubuntu/Debian only."
            exit 1
            ;;
    esac
}

ensure_env_file() {
    if [[ -f "${ENV_FILE}" ]]; then
        return
    fi

    if [[ ! -f "${ENV_EXAMPLE}" ]]; then
        log_error ".env.example not found."
        exit 1
    fi

    cp "${ENV_EXAMPLE}" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    log_warn "Created ${ENV_FILE} from template."
    log_warn "Fill BOT_TOKEN (and optional values), then rerun install.sh."
    exit 0
}

load_env() {
    set -a
    # shellcheck source=/dev/null
    source "${ENV_FILE}"
    set +a

    if [[ -z "${BOT_TOKEN:-}" || "${BOT_TOKEN}" == "your_telegram_bot_token" ]]; then
        log_error "BOT_TOKEN is missing in ${ENV_FILE}."
        exit 1
    fi

    INSTALL_DIR="${INSTALL_DIR:-/opt/rszd}"
    SERVICE_NAME="${SERVICE_NAME:-rszd}"
    DOWNLOAD_DIR="${DOWNLOAD_DIR:-downloads}"
    COOKIES_DIR="${COOKIES_DIR:-cookies}"
    RUNTIME_DOWNLOAD_DIR="$(resolve_runtime_path "${DOWNLOAD_DIR}")"
    RUNTIME_COOKIES_DIR="$(resolve_runtime_path "${COOKIES_DIR}")"
}

install_system_packages() {
    log_info "Installing system dependencies..."
    apt-get update -y
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        python3 \
        python3-venv \
        python3-pip \
        ffmpeg \
        git \
        rsync
    log_ok "System dependencies installed"
}

sync_project() {
    log_info "Syncing project to ${INSTALL_DIR}..."
    mkdir -p "${INSTALL_DIR}"
    rsync -a --delete \
        --exclude '.git' \
        --exclude '.env' \
        --exclude 'venv' \
        --exclude '__pycache__' \
        --exclude '.pytest_cache' \
        --exclude 'downloads' \
        --exclude 'cookies' \
        --exclude '*.db' \
        "${SCRIPT_DIR}/" "${INSTALL_DIR}/"

    install -m 600 "${ENV_FILE}" "${INSTALL_DIR}/.env"
    mkdir -p "${RUNTIME_DOWNLOAD_DIR}" "${RUNTIME_COOKIES_DIR}"
    log_ok "Project synced"
}

setup_virtualenv() {
    log_info "Creating virtual environment..."
    python3 -m venv "${INSTALL_DIR}/venv"
    "${INSTALL_DIR}/venv/bin/pip" install --upgrade pip
    "${INSTALL_DIR}/venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"
    log_ok "Virtual environment ready"
}

install_systemd_service() {
    local service_path="/etc/systemd/system/${SERVICE_NAME}.service"
    log_info "Installing systemd service ${SERVICE_NAME}..."
    cat > "${service_path}" <<EOF
[Unit]
Description=RSZD Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/main.py
Restart=always
RestartSec=5
TimeoutStopSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}"
    systemctl restart "${SERVICE_NAME}"
    log_ok "Systemd service installed"
}

print_summary() {
    echo
    log_ok "Installation completed"
    echo "Project: ${INSTALL_DIR}"
    echo "Service: ${SERVICE_NAME}"
    echo "Status:  systemctl status ${SERVICE_NAME}"
    echo "Logs:    journalctl -u ${SERVICE_NAME} -f"
}

main() {
    require_root
    ensure_supported_os
    ensure_env_file
    load_env
    install_system_packages
    sync_project
    setup_virtualenv
    install_systemd_service
    print_summary
}

main "$@"
