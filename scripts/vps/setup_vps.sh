#!/bin/bash
#
# VPS Setup for Nothing Ever Happens Bot
# Run with: bash setup_vps.sh
#
# Installs:
# - Python 3.11+ with venv
# - System dependencies
# - Application user and directories
# - Python packages

set -e

APP_USER="nothingbot"
APP_HOME="/home/${APP_USER}/nothing-ever-happens"
PYTHON_VERSION="3.11"

echo "🔧 Setting up VPS for Nothing Ever Happens Bot..."

# Check if running as non-root (should be run as regular user first for setup)
if [[ $EUID -eq 0 ]]; then
    echo "⚠️  Running as root. This script should be run as a regular user."
    echo "   However, some steps require sudo. We'll handle that..."
fi

# Detect OS
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    OS=$ID
fi

if [[ "$OS" != "ubuntu" && "$OS" != "debian" ]]; then
    echo "❌ This script only supports Ubuntu/Debian"
    exit 1
fi

# Install system dependencies
echo "📦 Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3-pip \
    git \
    curl \
    build-essential \
    libpq-dev \
    > /dev/null 2>&1

echo "✅ System dependencies installed"

# Create application user (if not exists)
if ! id "$APP_USER" &>/dev/null; then
    echo "👤 Creating application user: ${APP_USER}..."
    sudo useradd -m -s /bin/bash "${APP_USER}"
    echo "✅ User created"
else
    echo "ℹ️  User ${APP_USER} already exists"
fi

# Set up project directory
if [[ ! -d "$APP_HOME" ]]; then
    echo "📁 Setting up project directory: ${APP_HOME}..."
    sudo mkdir -p "$APP_HOME"
    sudo chown "${APP_USER}:${APP_USER}" "$APP_HOME"
    echo "✅ Project directory created"
else
    echo "ℹ️  Project directory already exists"
fi

# Copy repository to app home (if running from different location)
CURRENT_DIR="$(pwd)"
if [[ "$CURRENT_DIR" != "$APP_HOME" ]]; then
    echo "📋 Copying repository files..."
    # Check if we're in the right repo
    if [[ ! -f "$CURRENT_DIR/bot/main.py" ]]; then
        echo "❌ Not in repository root (missing bot/main.py)"
        exit 1
    fi
    sudo cp -r "$CURRENT_DIR"/* "$APP_HOME/" 2>/dev/null || true
    sudo chown -R "${APP_USER}:${APP_USER}" "$APP_HOME"
fi

# Create virtual environment
echo "🐍 Creating Python virtual environment..."
sudo -u "${APP_USER}" python3.11 -m venv "$APP_HOME/.venv"
echo "✅ Virtual environment created"

# Install Python packages
echo "📦 Installing Python packages..."
sudo -u "${APP_USER}" "$APP_HOME/.venv/bin/pip" install --quiet --upgrade pip setuptools wheel
sudo -u "${APP_USER}" "$APP_HOME/.venv/bin/pip" install --quiet -r "$APP_HOME/requirements.txt"
echo "✅ Python packages installed"

# Create directories
echo "📁 Creating application directories..."
sudo -u "${APP_USER}" mkdir -p "$APP_HOME/logs"
sudo -u "${APP_USER}" mkdir -p "$APP_HOME/data"
echo "✅ Directories created"

# Set up config files
if [[ ! -f "$APP_HOME/.env" ]]; then
    echo "⚙️  Creating .env file..."
    sudo cp "$APP_HOME/.env.example" "$APP_HOME/.env"
    sudo chown "${APP_USER}:${APP_USER}" "$APP_HOME/.env"
    sudo chmod 600 "$APP_HOME/.env"
    echo "⚠️  Edit $APP_HOME/.env and add your PRIVATE_KEY"
else
    echo "ℹ️  .env already exists"
fi

if [[ ! -f "$APP_HOME/config.json" ]]; then
    echo "⚙️  Creating config.json file..."
    sudo cp "$APP_HOME/config.example.json" "$APP_HOME/config.json"
    sudo chown "${APP_USER}:${APP_USER}" "$APP_HOME/config.json"
    echo "⚠️  Edit $APP_HOME/config.json with your settings"
else
    echo "ℹ️  config.json already exists"
fi

# Verify installation
echo ""
echo "✅ VPS Setup Complete!"
echo ""
echo "📋 Verification:"
PYTHON_EXEC="$APP_HOME/.venv/bin/python"
if [[ -f "$PYTHON_EXEC" ]]; then
    PYTHON_VER=$($PYTHON_EXEC --version)
    echo "   ✅ Python: $PYTHON_VER"
else
    echo "   ❌ Python executable not found"
fi

if [[ -f "$APP_HOME/requirements.txt" ]]; then
    echo "   ✅ Requirements file found"
fi

if [[ -f "$APP_HOME/.env" ]]; then
    echo "   ✅ .env file created"
fi

if [[ -f "$APP_HOME/config.json" ]]; then
    echo "   ✅ config.json file created"
fi

echo ""
echo "📚 Next Steps:"
echo "   1. Edit config files:"
echo "      - $APP_HOME/.env (add PRIVATE_KEY, DATABASE_URL if needed)"
echo "      - $APP_HOME/config.json (configure strategy, RPC URL, etc.)"
echo ""
echo "   2. Test the bot in dry-run mode:"
echo "      sudo -u ${APP_USER} ${PYTHON_EXEC} -m bot.main"
echo ""
echo "   3. Install systemd service:"
echo "      sudo bash scripts/vps/install_service.sh"
echo ""
echo "📍 Application home: $APP_HOME"
echo "👤 Application user: $APP_USER"
echo "🐍 Python binary: $PYTHON_EXEC"
