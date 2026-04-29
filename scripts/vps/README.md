# VPS Deployment Scripts

Complete production deployment scripts for Nothing Ever Happens bot on a VPS.

## Quick Start

```bash
# 1. SSH into fresh Ubuntu/Debian server
ssh root@your-vps-ip

# 2. Clone repository and enter directory
git clone <repo-url> && cd nothing-ever-happens

# 3. Run full deployment (all steps in sequence)
bash scripts/vps/deploy.sh
```

## Scripts Overview

### `deploy.sh` - Complete Deployment
**Orchestrates all deployment steps in sequence.**

```bash
sudo bash scripts/vps/deploy.sh
```

- ✅ PostgreSQL setup (database + user)
- ✅ System dependencies and Python environment
- ✅ Configuration file setup
- ✅ Dry-run test
- ✅ Systemd service installation
- ✅ Service startup
- ✅ Verification

### `setup_postgres.sh` - Database Setup
**Creates PostgreSQL database and application user.**

```bash
sudo bash scripts/vps/setup_postgres.sh
```

What it does:
- Installs PostgreSQL 14+
- Creates `nothing_happens` database
- Creates `nothingappuser` with restricted permissions
- Generates secure password
- Tests connection

Output: Connection string for `.env` file

**Run first if: You're setting up fresh database infrastructure**

### `setup_vps.sh` - System & Python Setup
**Prepares server with Python environment and dependencies.**

```bash
bash scripts/vps/setup_vps.sh
```

What it does:
- Installs system dependencies (Python 3.11+, git, build tools, etc.)
- Creates `nothingbot` application user
- Sets up project directories
- Creates Python virtual environment
- Installs Python packages from requirements.txt
- Creates config files (.env, config.json)

**Run second**

### `install_service.sh` - Systemd Service
**Installs bot as a systemd service for auto-start and monitoring.**

```bash
sudo bash scripts/vps/install_service.sh
```

What it does:
- Creates `/etc/systemd/system/nothing-happens-bot.service`
- Configures auto-restart on failure
- Sets up logging to systemd journal
- Enables service management

Service commands:
```bash
sudo systemctl start nothing-happens-bot     # Start
sudo systemctl stop nothing-happens-bot      # Stop
sudo systemctl restart nothing-happens-bot   # Restart
sudo systemctl status nothing-happens-bot    # Status
sudo systemctl enable nothing-happens-bot    # Enable auto-boot
sudo journalctl -u nothing-happens-bot -f    # View logs (live)
```

**Run third**

### `health_check.sh` - Health Monitoring
**Diagnostic tool to verify system health.**

```bash
bash scripts/vps/health_check.sh
```

Checks:
- Service status (running/stopped)
- Database connectivity
- Dashboard port (8080)
- Config files validity
- Recent error logs
- Disk space
- Memory usage
- Python environment

**Run anytime to diagnose issues**

### `run.sh` - Manual Execution
**Run bot outside of systemd (for testing/development).**

```bash
bash scripts/vps/run.sh [config_path]
```

Useful for:
- Testing with custom config
- Manual testing before service deployment
- Debugging in foreground

Example:
```bash
bash scripts/vps/run.sh config-staging.json
```

## Step-by-Step Manual Deployment

If you prefer to run steps individually:

```bash
# 1. Setup database (requires sudo)
sudo bash scripts/vps/setup_postgres.sh
# ➜ Saves connection string

# 2. Setup system and Python
bash scripts/vps/setup_vps.sh
# ➜ Creates nothingbot user and venv

# 3. Configure files
# Edit /home/nothingbot/nothing-ever-happens/.env
# Edit /home/nothingbot/nothing-ever-happens/config.json

# 4. Test in dry-run mode
sudo -u nothingbot /home/nothingbot/nothing-ever-happens/.venv/bin/python -m bot.main
# Watch logs for ~30 seconds, then Ctrl+C

# 5. Install service
sudo bash scripts/vps/install_service.sh

# 6. Start service
sudo systemctl start nothing-happens-bot

# 7. Verify
bash scripts/vps/health_check.sh
```

## Configuration Files

After running setup scripts, edit these files:

### `/home/nothingbot/nothing-ever-happens/.env`
```bash
# REQUIRED: Private key for trading wallet
PRIVATE_KEY=0x...

# REQUIRED if using DB (likely): PostgreSQL connection
DATABASE_URL=postgres://nothingappuser:password@localhost:5432/nothing_happens

# OPTIONAL: Log level
LOG_LEVEL=INFO
```

### `/home/nothingbot/nothing-ever-happens/config.json`
```json
{
  "connection": {
    "polygon_rpc_url": "https://...",  // Get free tier from Alchemy
    "funder_address": "0x..."          // Wallet address
  },
  "deployment": {
    "bot_mode": "paper",               // Change to "live" when ready
    "live_trading_enabled": false,     // Change to true for real trades
    "dry_run": true,                   // Set to false for orders
    "database_url": null,              // Or from .env
    "dashboard_port": 8080
  },
  "strategies": {
    "nothing_happens": {
      "max_entry_price": 0.95,
      "min_entry_price": 0.0,
      "cash_pct_per_trade": 0.005,
      "risk_config": {
        "max_total_open_exposure_usd": 1500.0,
        "max_market_open_exposure_usd": 1000.0,
        "max_daily_drawdown_usd": 0.0
      }
      // ... other strategy params
    }
  }
}
```

## Monitoring

### View live logs
```bash
sudo journalctl -u nothing-happens-bot -f
```

### View last N lines
```bash
sudo journalctl -u nothing-happens-bot -n 100
```

### Access dashboard
```
http://<vps-ip>:8080
```

### Run health check
```bash
bash scripts/vps/health_check.sh
```

## Troubleshooting

### Bot won't start
```bash
# Check systemd status
systemctl status nothing-happens-bot

# View recent errors
sudo journalctl -u nothing-happens-bot -n 50

# Test manually
sudo -u nothingbot /home/nothingbot/nothing-ever-happens/.venv/bin/python -m bot.main
```

### Database connection error
```bash
# Test PostgreSQL connection
psql postgres://nothingappuser:password@localhost:5432/nothing_happens

# Check PostgreSQL service
sudo systemctl status postgresql

# View PostgreSQL logs
sudo tail -f /var/log/postgresql/postgresql*.log
```

### High memory/CPU
- Reduce polling intervals in config.json
- Check for runaway redeemer task
- Monitor with `bash scripts/vps/health_check.sh`

## Security Best Practices

1. **Protect .env file**
   ```bash
   chmod 600 /home/nothingbot/nothing-ever-happens/.env
   ```

2. **Regular backups**
   ```bash
   tar -czf backup-$(date +%s).tar.gz \
     /home/nothingbot/nothing-ever-happens/.env \
     /home/nothingbot/nothing-ever-happens/config.json
   ```

3. **Database backups**
   ```bash
   pg_dump $DATABASE_URL > backup.sql
   ```

4. **SSH key auth** (disable password)
5. **Firewall** (restrict dashboard port if needed)
6. **Monitor logs** for suspicious activity

## Rollback

If something breaks:

```bash
# Stop service
sudo systemctl stop nothing-happens-bot

# Restore from backup
tar -xzf backup-*.tar.gz -C /home/nothingbot/nothing-ever-happens/

# Check database integrity
psql $DATABASE_URL -c "SELECT 1;"

# Restart
sudo systemctl start nothing-happens-bot

# Verify
bash scripts/vps/health_check.sh
```

## Environment Variables Reference

All can be overridden from `.env` or systemd service file:

```bash
# Database
DATABASE_URL=postgres://...

# Control
BOT_MODE=paper|live
LIVE_TRADING_ENABLED=true|false
DRY_RUN=true|false
LOG_LEVEL=INFO|DEBUG|WARNING

# Strategy (overrides config.json)
PM_NH_MAX_ENTRY_PRICE=0.95
PM_NH_MIN_ENTRY_PRICE=0.0
PM_NH_CASH_PCT_PER_TRADE=0.005

# Risk (overrides config.json)
PM_RISK_MAX_TOTAL_OPEN_EXPOSURE_USD=1500
PM_RISK_MAX_MARKET_OPEN_EXPOSURE_USD=1000
PM_RISK_MAX_DAILY_DRAWDOWN_USD=0
```

See `bot/config.py` for complete list.
