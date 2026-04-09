#!/bin/bash
set -euo pipefail

# --- Validate required environment ---
HOSTS="${HOSTS:-}"
INTERVAL="${INTERVAL:-0 */6 * * *}"

if [ -z "$HOSTS" ]; then
  echo "ERROR: No hosts provided via HOSTS env variable. Exiting."
  exit 1
fi

echo "HOSTS received: $HOSTS"
echo "INTERVAL set to: $INTERVAL"

# --- Write cron job dynamically ---
mkdir -p /etc/cron.d /data

CRON_FILE=/etc/cron.d/daily-tests
# Cron treats '%' as newline — escape them
HOSTS_ESCAPED="${HOSTS//%/\\%}"
# /etc/cron.d/ files require a username field (no user crontab to avoid double execution)
echo "${INTERVAL} root /usr/bin/python3 /usr/src/app/periodic.py --hosts ${HOSTS_ESCAPED} --output-dir /data >> /data/cron.log 2>&1" > "$CRON_FILE"
echo "" >> "$CRON_FILE"  # trailing newline required by cron
chmod 0644 "$CRON_FILE"

echo "Cron job added for hosts: ${HOSTS} at interval: ${INTERVAL}"

# --- Graceful shutdown on SIGTERM ---
cleanup() {
  echo "Received SIGTERM, shutting down..."
  exit 0
}
trap cleanup SIGTERM SIGINT

# --- Detect cron binary and start in foreground ---
CRON_BIN=$(which cron 2>/dev/null || which crond 2>/dev/null || "")

if [ -z "$CRON_BIN" ]; then
  echo "ERROR: Neither cron nor crond found. Exiting."
  exit 1
fi

echo "Starting cron daemon: $CRON_BIN"

case "$CRON_BIN" in
  */cron)  exec cron -f ;;
  */crond) exec crond -n ;;
esac
