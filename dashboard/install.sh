#!/usr/bin/env bash
# ── postwatch-dashboard installer ──────────────────────────────────────
set -euo pipefail

INSTALL_DIR="/opt/postwatch-dashboard"

# Must run as root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root." >&2
    exit 1
fi

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed. Please install Docker first." >&2
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "ERROR: docker-compose is not installed. Please install docker-compose first." >&2
    exit 1
fi

echo "==> Installing postwatch-dashboard to ${INSTALL_DIR}"

# Create install directory
mkdir -p "${INSTALL_DIR}"

# Copy application files
echo "==> Copying application files"
cp app.py "${INSTALL_DIR}/app.py"
cp config.py "${INSTALL_DIR}/config.py"
cp models.py "${INSTALL_DIR}/models.py"
cp poller.py "${INSTALL_DIR}/poller.py"
cp requirements.txt "${INSTALL_DIR}/requirements.txt"
cp Dockerfile "${INSTALL_DIR}/Dockerfile"
cp docker-compose.yml "${INSTALL_DIR}/docker-compose.yml"

# Copy directories
cp -r templates "${INSTALL_DIR}/templates"
cp -r static "${INSTALL_DIR}/static"

# Create data directory for SQLite volume
mkdir -p "${INSTALL_DIR}/data"

# Only copy .env if it doesn't already exist (don't overwrite config)
if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
    cp .env.example "${INSTALL_DIR}/.env"
    echo "    Copied .env.example → .env (edit this before starting!)"
else
    echo "    .env already exists — skipping (won't overwrite your config)"
fi

# Set proper permissions
chmod 755 "${INSTALL_DIR}"
find "${INSTALL_DIR}" -type f -exec chmod 644 {} +
find "${INSTALL_DIR}" -type d -exec chmod 755 {} +

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Installation complete!"
echo ""
echo "  Before running docker-compose, edit the config:"
echo "    nano ${INSTALL_DIR}/.env"
echo ""
echo "  Next steps:"
echo "    1. Edit the config:  nano ${INSTALL_DIR}/.env"
echo "    2. Set SECRET_KEY, ADMIN_USER, ADMIN_PASS, AGENT_API_KEY"
echo "    3. Configure AGENTS with your agent URLs (e.g. http://192.168.1.10:5100)"
echo "    4. Start the dashboard:"
echo "         cd ${INSTALL_DIR}"
echo "         docker-compose up --build"
echo "    5. Access at http://localhost:5000 (or mapped port if behind proxy)"
echo "════════════════════════════════════════════════════════════════"
