#!/usr/bin/env bash
# ── postwatch-agent installer ──────────────────────────────────────────
set -euo pipefail

INSTALL_DIR="/opt/postwatch-agent"

# Must run as root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root." >&2
    exit 1
fi

echo "==> Installing postwatch-agent to ${INSTALL_DIR}"

# Create install directory
mkdir -p "${INSTALL_DIR}"

# Copy application files
cp agent.py "${INSTALL_DIR}/agent.py"

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
