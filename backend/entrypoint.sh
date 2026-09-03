#!/bin/bash
set -e

# --- Wait for Postgres to be ready ---
echo "[entrypoint] Waiting for Postgres..."
for i in $(seq 1 30); do
    if pg_isready -h "${POSTGRES_HOST:-postgres}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-content_tracker}" 2>/dev/null; then
        echo "[entrypoint] Postgres is ready"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "[entrypoint] WARNING: Postgres not ready after 30s, trying anyway..."
    fi
    sleep 1
done

# --- Run migrations ---
echo "[entrypoint] Running Alembic migrations..."
alembic upgrade head

echo "[entrypoint] Ensuring initial data..."
python -m app.db.seed

# --- Start the app ---
echo "[entrypoint] Starting API..."
exec "$@"
