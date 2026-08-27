#!/bin/bash
# Content Tracker — one-command setup
# Usage: ./setup.sh

set -e

echo "=== Content Tracker Setup ==="

# 1. Create .env from example if missing
if [ ! -f .env ]; then
    echo "[setup] Creating .env from .env.example..."
    cp .env.example .env
    echo "[setup] .env created. Edit it to set passwords and API keys."
fi

# 2. Create data directories
mkdir -p data/postgres backend/uploads

# 3. Build and start
echo "[setup] Building and starting containers..."
docker compose up --build -d

echo ""
echo "=== Done ==="
echo "  Web:  http://localhost:5000"
echo "  API:  http://localhost:8000/docs"
echo ""
echo "Next steps:"
echo "  1. Open http://localhost:5000 and register"
echo "  2. Go to /admin/settings to configure platform tokens and proxies"
