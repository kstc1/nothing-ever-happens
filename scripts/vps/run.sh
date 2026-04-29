#!/bin/bash
#
# Simple runner for Nothing Ever Happens Bot
# For testing or manual execution
# Usage: bash run.sh [config_path]

set -e

APP_HOME="/home/nothingbot/nothing-ever-happens"

# Allow override from command line
CONFIG_PATH="${1:-config.json}"

# Check if running from app home or current directory
if [[ -f "./bot/main.py" ]]; then
    EXEC_DIR="."
    VENV_PYTHON="./.venv/bin/python"
elif [[ -f "$APP_HOME/bot/main.py" ]]; then
    EXEC_DIR="$APP_HOME"
    VENV_PYTHON="$APP_HOME/.venv/bin/python"
else
    echo "❌ Could not find bot/main.py"
    echo "   Please run from repository root or set APP_HOME correctly"
    exit 1
fi

# Verify virtual environment
if [[ ! -f "$VENV_PYTHON" ]]; then
    echo "❌ Python virtual environment not found at $VENV_PYTHON"
    echo "   Run setup_vps.sh first"
    exit 1
fi

# Load environment
if [[ -f "$EXEC_DIR/.env" ]]; then
    set -a
    source "$EXEC_DIR/.env"
    set +a
else
    echo "⚠️  .env file not found, relying on system environment"
fi

# Verify config file
if [[ ! -f "$EXEC_DIR/$CONFIG_PATH" ]]; then
    echo "❌ Config file not found: $EXEC_DIR/$CONFIG_PATH"
    exit 1
fi

echo "🚀 Starting Nothing Ever Happens Bot..."
echo "   Config: $CONFIG_PATH"
echo "   Working Directory: $EXEC_DIR"
echo ""

# Run bot
cd "$EXEC_DIR"
export CONFIG_PATH="$CONFIG_PATH"
exec "$VENV_PYTHON" -m bot.main "$@"
