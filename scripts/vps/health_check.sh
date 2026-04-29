#!/bin/bash
#
# Health Check for Nothing Ever Happens Bot
# Run with: bash health_check.sh
# 
# Checks:
# - Service status
# - Database connectivity
# - Process health
# - Port availability
# - Recent logs for errors

set -e

APP_USER="nothingbot"
APP_HOME="/home/${APP_USER}/nothing-ever-happens"
SERVICE_NAME="nothing-happens-bot"
DASHBOARD_PORT="8080"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🏥 Nothing Ever Happens Bot - Health Check${NC}"
echo ""

# Check 1: Service Status
echo -n "📊 Service Status: "
if systemctl is-active --quiet ${SERVICE_NAME}; then
    echo -e "${GREEN}✅ Running${NC}"
    SERVICE_PID=$(systemctl show -p MainPID --value ${SERVICE_NAME})
    echo "   Process ID: $SERVICE_PID"
else
    echo -e "${RED}❌ Not Running${NC}"
    echo "   Start with: sudo systemctl start ${SERVICE_NAME}"
fi

# Check 2: Database Connection
echo -n "🗄️  Database Connection: "
if [[ -f "$APP_HOME/.env" ]]; then
    DB_URL=$(grep "DATABASE_URL" "$APP_HOME/.env" | cut -d= -f2- 2>/dev/null || echo "")
    if [[ -z "$DB_URL" ]]; then
        echo -e "${YELLOW}⚠️  Not configured${NC}"
    else
        # Try to connect
        if PGPASSWORD="" psql "$DB_URL" -c "SELECT 1;" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ Connected${NC}"
        else
            echo -e "${RED}❌ Connection Failed${NC}"
            echo "   Check DATABASE_URL in .env"
        fi
    fi
else
    echo -e "${YELLOW}⚠️  .env not found${NC}"
fi

# Check 3: Dashboard Port
echo -n "🌐 Dashboard Port ($DASHBOARD_PORT): "
if netstat -tlnp 2>/dev/null | grep -q ":$DASHBOARD_PORT "; then
    echo -e "${GREEN}✅ Listening${NC}"
    echo "   Access: http://localhost:$DASHBOARD_PORT"
else
    echo -e "${YELLOW}⚠️  Not listening${NC}"
    echo "   Service may not be fully started yet"
fi

# Check 4: Config Files
echo -n "⚙️  Config Files: "
if [[ -f "$APP_HOME/config.json" && -f "$APP_HOME/.env" ]]; then
    echo -e "${GREEN}✅ Both present${NC}"
    
    # Validate JSON
    if python3 -m json.tool "$APP_HOME/config.json" > /dev/null 2>&1; then
        echo "   JSON syntax: ✅"
    else
        echo "   JSON syntax: ❌ Invalid"
    fi
else
    echo -e "${RED}❌ Missing${NC}"
fi

# Check 5: Recent Log Errors
echo ""
echo -n "📋 Recent Errors in Logs: "
ERROR_COUNT=$(journalctl -u ${SERVICE_NAME} -n 100 --no-pager 2>/dev/null | grep -i "error\|exception\|failed" | wc -l || echo "0")
if [[ $ERROR_COUNT -gt 0 ]]; then
    echo -e "${YELLOW}⚠️  $ERROR_COUNT found${NC}"
    echo "   Run: sudo journalctl -u ${SERVICE_NAME} -n 50"
else
    echo -e "${GREEN}✅ None${NC}"
fi

# Check 6: Disk Space
echo -n "💾 Disk Space: "
DISK_USAGE=$(df "$APP_HOME" | tail -1 | awk '{print $5}' | sed 's/%//')
if [[ $DISK_USAGE -gt 90 ]]; then
    echo -e "${RED}❌ Critical ($DISK_USAGE%)${NC}"
elif [[ $DISK_USAGE -gt 75 ]]; then
    echo -e "${YELLOW}⚠️  Warning ($DISK_USAGE%)${NC}"
else
    echo -e "${GREEN}✅ Healthy ($DISK_USAGE%)${NC}"
fi

# Check 7: Memory Usage (if running)
if systemctl is-active --quiet ${SERVICE_NAME}; then
    echo -n "🧠 Memory Usage: "
    MEM_KB=$(ps aux | grep "[p]ython -m bot.main" | awk '{print $6}' | head -1)
    if [[ -n "$MEM_KB" ]]; then
        MEM_MB=$((MEM_KB / 1024))
        echo -e "${GREEN}$MEM_MB MB${NC}"
    else
        echo -e "${YELLOW}N/A${NC}"
    fi
fi

# Check 8: Python Environment
echo -n "🐍 Python Environment: "
VENV_PYTHON="$APP_HOME/.venv/bin/python"
if [[ -f "$VENV_PYTHON" ]]; then
    PYTHON_VER=$($VENV_PYTHON --version 2>&1)
    echo -e "${GREEN}✅ $PYTHON_VER${NC}"
else
    echo -e "${RED}❌ Venv not found${NC}"
fi

echo ""
echo -e "${BLUE}📚 Common Commands:${NC}"
echo "  View logs:       sudo journalctl -u ${SERVICE_NAME} -f"
echo "  View last 50:    sudo journalctl -u ${SERVICE_NAME} -n 50"
echo "  Restart service: sudo systemctl restart ${SERVICE_NAME}"
echo "  Stop service:    sudo systemctl stop ${SERVICE_NAME}"
echo "  Service status:  systemctl status ${SERVICE_NAME}"
echo ""

# Overall status
echo -n "🎯 Overall Status: "
if systemctl is-active --quiet ${SERVICE_NAME}; then
    echo -e "${GREEN}✅ Operational${NC}"
else
    echo -e "${RED}❌ Not Operational${NC}"
fi

echo ""
