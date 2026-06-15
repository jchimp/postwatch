#!/usr/bin/env bash
# ── postwatch-agent installer ──────────────────────────────────────────
set -euo pipefail

INSTALL_DIR="/opt/postwatch-agent"

# Must run as root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root." >&2
    exit 1
fi

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed." >&2
    exit 1
fi

echo "==> Installing postwatch-agent to ${INSTALL_DIR}"

# Create install directory
mkdir -p "${INSTALL_DIR}"

# Copy application files
echo "==> Copying application files"
cp agent.py "${INSTALL_DIR}/agent.py"
cp postwatch-agent.service "${INSTALL_DIR}/postwatch-agent.service"

# Only copy .env if it doesn't already exist (don't overwrite config)
if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
    cp .env.example "${INSTALL_DIR}/.env"
    echo "    Copied .env.example → .env (edit this before starting!)"
else
    echo "    .env already exists — skipping (won't overwrite your config)"
fi

# Create Python virtual environment
echo "==> Creating Python virtual environment"
python3 -m venv "${INSTALL_DIR}/venv"

# Install dependencies
echo "==> Installing Python dependencies"
"${INSTALL_DIR}/venv/bin/pip" install --quiet --upgrade pip
"${INSTALL_DIR}/venv/bin/pip" install --quiet flask python-dotenv

# Install systemd unit
echo "==> Installing systemd service"
cp postwatch-agent.service /etc/systemd/system/postwatch-agent.service
systemctl daemon-reload

# Enable firewall for port 5100
echo "==> Enabling UFW for port 5100"
if command -v ufw &> /dev/null; then
    ufw allow 5100/tcp
    echo "    UFW rule added for port 5100"
else
    echo "    WARNING: UFW not found or not installed"
fi

# Set proper permissions
echo "==> Setting permissions"
chmod 755 "${INSTALL_DIR}"
chmod 755 "${INSTALL_DIR}/venv"
chmod 644 "${INSTALL_DIR}/agent.py"
chmod 644 "${INSTALL_DIR}/.env"
chmod 644 "${INSTALL_DIR}/postwatch-agent.service"
find "${INSTALL_DIR}/venv" -type d -exec chmod 755 {} +
find "${INSTALL_DIR}/venv" -type f -exec chmod 644 {} +

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Installation complete!"
echo ""
echo "  Next steps:"
echo "    1. Edit the config:  nano ${INSTALL_DIR}/.env"
echo "    2. Set a strong API_KEY and your SERVER_NAME"
echo "    3. Start the service:"
echo "         systemctl enable --now postwatch-agent"
echo "    4. Check status:"
echo "         systemctl status postwatch-agent"
echo "         journalctl -u postwatch-agent -f"
echo "════════════════════════════════════════════════════════════════"
