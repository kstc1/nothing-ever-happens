#!/bin/bash
#
# PostgreSQL Setup for Nothing Ever Happens Bot
# Run with: sudo bash setup_postgres.sh
# 
# Creates:
# - PostgreSQL database (nothing_happens)
# - Application user (nothingappuser) with restricted permissions
# - Connection configuration

set -e

POSTGRES_VERSION="14"
DB_NAME="nothing_happens"
DB_USER="nothingappuser"
DB_PASSWORD="${DB_PASSWORD:-}" # Allow override via env var

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo "❌ This script must be run as root (use: sudo bash setup_postgres.sh)"
    exit 1
fi

echo "🔧 Setting up PostgreSQL for Nothing Ever Happens..."

# Update package lists
echo "📦 Updating package lists..."
apt-get update -qq

# Install PostgreSQL
echo "📥 Installing PostgreSQL ${POSTGRES_VERSION}..."
apt-get install -y -qq postgresql postgresql-contrib > /dev/null 2>&1

# Check if PostgreSQL is running
echo "🚀 Starting PostgreSQL service..."
systemctl start postgresql
systemctl enable postgresql
sleep 2

# Generate secure password if not provided
if [[ -z "$DB_PASSWORD" ]]; then
    DB_PASSWORD=$(openssl rand -base64 32 | tr -d '=' | tr -d '+' | cut -c1-20)
fi

echo "🔐 Creating database and user..."

# Create database and user (run as postgres user)
sudo -u postgres psql << EOSQL
-- Create database
CREATE DATABASE ${DB_NAME};

-- Create user
CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';

-- Grant privileges (schema + tables)
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};

-- Connect to database and set default privileges
\c ${DB_NAME}
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO ${DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO ${DB_USER};
EOSQL

echo ""
echo "✅ PostgreSQL Setup Complete!"
echo ""
echo "📋 Database Information:"
echo "   Database name: ${DB_NAME}"
echo "   User: ${DB_USER}"
echo "   Password: ${DB_PASSWORD}"
echo ""
echo "🔗 Connection String for .env or config.json:"
echo "   DATABASE_URL=postgres://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}"
echo ""
echo "⚠️  IMPORTANT: Save this password securely!"
echo "   Add to .env file with restricted permissions (600)"
echo ""

# Verify connection
echo "✔️  Testing connection..."
if PGPASSWORD="${DB_PASSWORD}" psql -U "${DB_USER}" -d "${DB_NAME}" -h localhost -c "SELECT 1;" > /dev/null 2>&1; then
    echo "✅ Connection test successful!"
else
    echo "❌ Connection test failed. Check PostgreSQL logs."
    exit 1
fi

echo ""
echo "📚 Next Steps:"
echo "   1. Save the connection string above"
echo "   2. Add DATABASE_URL to .env or config.json"
echo "   3. Run: bash scripts/vps/setup_vps.sh"
