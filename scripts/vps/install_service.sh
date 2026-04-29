#!/bin/bash
#
# Install Nothing Ever Happens Bot as Systemd Service
# Run with: sudo bash scripts/vps/install_service.sh
#
# Creates systemd service file for auto-start and monitoring

set -e

APP_USER="nothingbot"
APP_HOME="/home/${APP_USER}/nothing-ever-happens"
SERVICE_NAME="nothing-happens-bot"

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo "❌ This script must be run as root (use: sudo bash install_service.sh)"
    exit 1
fi

echo "🔧 Installing systemd service..."

# Check if app directory exists
if [[ ! -d "$APP_HOME" ]]; then
    echo "❌ Application directory not found: $APP_HOME"
    echo "   Run setup_vps.sh first"
    exit 1
fi

# Check if .env exists
if [[ ! -f "$APP_HOME/.env" ]]; then
    echo "❌ .env file not found at $APP_HOME/.env"
    exit 1
fi

# Check if config.json exists
if [[ ! -f "$APP_HOME/config.json" ]]; then
    echo "❌ config.json file not found at $APP_HOME/config.json"
    exit 1
fi

# Create systemd service file
echo "📝 Creating systemd service file..."

cat > /etc/systemd/system/${SERVICE_NAME}.service << 'EOF'
[Unit]
Description=Nothing Ever Happens Bot (Polymarket)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nothingbot
Group=nothingbot
WorkingDirectory=/home/nothingbot/nothing-ever-happens

# Set environment variables
EnvironmentFile=/home/nothingbot/nothing-ever-happens/.env
Environment="CONFIG_PATH=/home/nothingbot/nothing-ever-happens/config.json"

# Start command
ExecStart=/home/nothingbot/nothing-ever-happens/.venv/bin/python -m bot.main

# Restart policy
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nothing-happens-bot

# Resource limits
LimitNOFILE=65536
LimitNPROC=4096

# Security (optional)
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# Update permissions
chmod 644 /etc/systemd/system/${SERVICE_NAME}.service

# Reload systemd daemon
echo "🔄 Reloading systemd daemon..."
systemctl daemon-reload

echo ""
echo "✅ Service installed successfully!"
echo ""
echo "📋 Service Management Commands:"
echo "   Start:     sudo systemctl start ${SERVICE_NAME}"
echo "   Stop:      sudo systemctl stop ${SERVICE_NAME}"
echo "   Status:    sudo systemctl status ${SERVICE_NAME}"
echo "   Logs:      sudo journalctl -u ${SERVICE_NAME} -f"
echo "   Enable:    sudo systemctl enable ${SERVICE_NAME}"
echo "   Disable:   sudo systemctl disable ${SERVICE_NAME}"
echo ""
echo "⚠️  Before starting service, ensure:"
echo "   - .env file has PRIVATE_KEY and DATABASE_URL"
echo "   - config.json is properly configured"
echo "   - Database is accessible"
echo ""
echo "🚀 To start the bot:"
echo "   sudo systemctl start ${SERVICE_NAME}"
echo ""
echo "📊 To monitor in real-time:"
echo "   sudo journalctl -u ${SERVICE_NAME} -f"
echo ""
echo "💡 To enable auto-start on boot:"
echo "   sudo systemctl enable ${SERVICE_NAME}"
