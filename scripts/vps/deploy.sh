#!/bin/bash
#
# VPS Deployment Sequence
# Complete setup from scratch on a fresh Ubuntu/Debian server
# 
# Prerequisites:
# - Root/sudo access on VPS
# - Domain name (optional)
# - Polygon RPC URL (free from Alchemy)
# 
# Total time: ~5-10 minutes
# 
# USAGE:
#   1. SSH into VPS
#   2. Clone repo: git clone <repo> && cd nothing-ever-happens
#   3. Run this script: bash scripts/vps/deploy.sh
#

set -e

STEP=1

step() {
    echo ""
    echo "=========================================="
    echo "Step $STEP: $1"
    echo "=========================================="
    ((STEP++))
}

info() {
    echo "ℹ️  $1"
}

warn() {
    echo "⚠️  $1"
}

success() {
    echo "✅ $1"
}

error() {
    echo "❌ $1"
    exit 1
}

# Verify we're in repo root
if [[ ! -f "bot/main.py" ]]; then
    error "Not in repository root. Run from repository directory."
fi

echo ""
echo "🚀 Nothing Ever Happens Bot - VPS Deployment"
echo "   Repository: $(pwd)"
echo ""

# Step 1: PostgreSQL
step "PostgreSQL Database Setup"
info "Setting up PostgreSQL database and user..."
if [[ -f "scripts/vps/setup_postgres.sh" ]]; then
    sudo bash scripts/vps/setup_postgres.sh
    success "PostgreSQL setup complete"
else
    error "setup_postgres.sh not found"
fi

# Step 2: System & Python
step "System and Python Environment Setup"
info "Installing dependencies and creating app user..."
if [[ -f "scripts/vps/setup_vps.sh" ]]; then
    bash scripts/vps/setup_vps.sh
    success "VPS setup complete"
else
    error "setup_vps.sh not found"
fi

# Step 3: Configuration
step "Configuration"
APP_HOME="/home/nothingbot/nothing-ever-happens"
info "Review and update configuration files at:"
echo ""
echo "   📝 Edit these files:"
echo "      $APP_HOME/.env"
echo "        - Add PRIVATE_KEY (your trading wallet private key)"
echo "        - Set DATABASE_URL (from PostgreSQL setup above)"
echo "        - Optional: Set LOG_LEVEL"
echo ""
echo "      $APP_HOME/config.json"
echo "        - Set connection.polygon_rpc_url"
echo "        - Verify strategy parameters"
echo "        - Review risk_config settings"
echo "        - Set deployment.bot_mode = 'live' (when ready)"
echo "        - Set deployment.live_trading_enabled = true (ONLY when testing complete)"
echo ""
info "Press ENTER when ready, or Ctrl+C to abort..."
read -r

# Step 4: Verify Configuration
step "Configuration Verification"
if [[ ! -f "$APP_HOME/.env" ]]; then
    error ".env file not found at $APP_HOME/.env"
fi

if [[ ! -f "$APP_HOME/config.json" ]]; then
    error "config.json file not found at $APP_HOME/config.json"
fi

# Check JSON syntax
if sudo -u nothingbot python3 -m json.tool "$APP_HOME/config.json" > /dev/null 2>&1; then
    success "config.json syntax valid"
else
    error "config.json has syntax errors"
fi

# Check .env has PRIVATE_KEY
if grep -q "PRIVATE_KEY=" "$APP_HOME/.env"; then
    info ".env file contains PRIVATE_KEY entry"
else
    warn ".env file missing PRIVATE_KEY - bot won't trade"
fi

# Step 5: Test Dry Run
step "Test in Dry-Run Mode"
info "Testing bot with dry_run=true..."
info "This will run the bot without making real trades"
echo ""
echo "   Run: sudo -u nothingbot $APP_HOME/.venv/bin/python -m bot.main"
echo ""
echo "   Watch for ~30 seconds, then Ctrl+C to stop"
echo ""
read -p "Ready to test? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    timeout 30 sudo -u nothingbot "$APP_HOME/.venv/bin/python" -m bot.main || true
    success "Dry-run test complete"
else
    warn "Skipping dry-run test"
fi

# Step 6: Install Service
step "Install Systemd Service"
if [[ -f "scripts/vps/install_service.sh" ]]; then
    sudo bash scripts/vps/install_service.sh
    success "Systemd service installed"
else
    error "install_service.sh not found"
fi

# Step 7: Start Service
step "Start Bot Service"
info "Starting bot as systemd service..."
sudo systemctl start nothing-happens-bot
sleep 3

if sudo systemctl is-active --quiet nothing-happens-bot; then
    success "Bot service started successfully"
    echo ""
    echo "📊 Service Status:"
    sudo systemctl status nothing-happens-bot
else
    error "Bot service failed to start. Check logs:"
    echo "   sudo journalctl -u nothing-happens-bot -n 50"
fi

# Step 8: Summary
echo ""
echo "=========================================="
echo "🎉 Deployment Complete!"
echo "=========================================="
echo ""
echo "📋 What's Running:"
echo "   ✅ PostgreSQL database (nothing_happens)"
echo "   ✅ Bot service (nothing-happens-bot)"
echo "   ✅ Dashboard (http://<vps-ip>:8080)"
echo ""
echo "📚 Next Steps:"
echo "   1. Monitor logs:"
echo "      sudo journalctl -u nothing-happens-bot -f"
echo ""
echo "   2. Check dashboard:"
echo "      http://<your-vps-ip>:8080"
echo ""
echo "   3. When ready for live trading:"
echo "      - Update config.json: bot_mode = 'live'"
echo "      - Update config.json: live_trading_enabled = true"
echo "      - Restart: sudo systemctl restart nothing-happens-bot"
echo ""
echo "⚠️  IMPORTANT REMINDERS:"
echo "   - Keep .env file secure (contains PRIVATE_KEY)"
echo "   - Regularly backup config.json and .env"
echo "   - Monitor bot logs for errors"
echo "   - Test risk controls before live trading"
echo ""
echo "🔗 Useful Commands:"
echo "   View logs:     sudo journalctl -u nothing-happens-bot -f"
echo "   Stop bot:      sudo systemctl stop nothing-happens-bot"
echo "   Restart bot:   sudo systemctl restart nothing-happens-bot"
echo "   Health check:  bash scripts/vps/health_check.sh"
echo "   Service logs:  sudo journalctl -u nothing-happens-bot -n 100"
echo ""
