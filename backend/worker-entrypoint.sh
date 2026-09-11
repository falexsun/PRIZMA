#!/bin/bash
# Auto-detect CPU cores and available RAM, then start the Celery worker
# with concurrency tuned to the machine's capacity.

set -e

TOTAL_CORES=$(nproc 2>/dev/null || echo 2)

# Detect available RAM (MB) — /proc/meminfo works in Docker without `free`
if [ -f /proc/meminfo ]; then
    TOTAL_RAM_MB=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
else
    TOTAL_RAM_MB=$(free -m 2>/dev/null | awk '/Mem:/ {print $2}')
fi
[ -z "$TOTAL_RAM_MB" ] || [ "$TOTAL_RAM_MB" -eq 0 ] 2>/dev/null && TOTAL_RAM_MB=2048

# Read overrides from env, or auto-calculate
if [ -n "$WORKER_CONCURRENCY" ]; then
    CONCURRENCY=$WORKER_CONCURRENCY
else
    WORKER_TYPE="${1:-fast}"

    if [ "$WORKER_TYPE" = "heavy" ]; then
        # Heavy worker: Playwright Chromium uses ~300-400MB per instance
        # Reserve 1GB for OS/redis/postgres overhead
        AVAILABLE_MB=$((TOTAL_RAM_MB - 1024))
        RAM_LIMIT=$(( AVAILABLE_MB / 400 ))
        [ $RAM_LIMIT -lt 1 ] && RAM_LIMIT=1
        CPU_LIMIT=$(( TOTAL_CORES / 2 ))
        [ $CPU_LIMIT -lt 1 ] && CPU_LIMIT=1
        # Take the lower of RAM-based and CPU-based limits
        if [ $RAM_LIMIT -lt $CPU_LIMIT ]; then
            CONCURRENCY=$RAM_LIMIT
        else
            CONCURRENCY=$CPU_LIMIT
        fi
        # Cap at 8 — more than that rarely helps with Playwright
        [ $CONCURRENCY -gt 8 ] && CONCURRENCY=8
    else
        # Fast worker: HTTP-based, lightweight (~50MB per instance)
        # Use most cores, leave 1 for the system
        CONCURRENCY=$(( TOTAL_CORES - 1 ))
        [ $CONCURRENCY -lt 2 ] && CONCURRENCY=2
        # Cap at 16
        [ $CONCURRENCY -gt 16 ] && CONCURRENCY=16
    fi
fi

echo "[auto-worker] type=${1:-fast} cores=$TOTAL_CORES ram=${TOTAL_RAM_MB}MB concurrency=$CONCURRENCY"

exec celery -A app.workers.celery_app worker \
    --loglevel=info \
    -Q "${2:-fast,celery}" \
    --concurrency="$CONCURRENCY"
