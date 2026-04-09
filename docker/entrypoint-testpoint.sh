#!/bin/bash
set -euo pipefail

# --- Validate required environment ---
if [ -z "${HOSTS:-}" ]; then
  echo "ERROR: HOSTS environment variable is not set. Exiting."
  exit 1
fi

# --- Read configuration from environment ---
CRON_EXPRESSION="${CRON_EXPRESSION:-0 */6 * * *}"
ARCHIVE_URLS="${ARCHIVE_URLS:-}"
AUTH_TOKEN="${AUTH_TOKEN:-}"
SCRIPT_PATH="/usr/src/app/periodic.py"
LOG_FILE="/data/pscheduler_cron.log"
PYTHON_BIN=$(which python3)

echo "HOSTS: $HOSTS"
echo "CRON_EXPRESSION: $CRON_EXPRESSION"
echo "ARCHIVE_URLS: $ARCHIVE_URLS"

# --- Set up cron job ---
mkdir -p /etc/cron.d /data

CRON_FILE=/etc/cron.d/pscheduler_cron

# Build cron command with optional flags
CRON_CMD="$PYTHON_BIN $SCRIPT_PATH --hosts $HOSTS --output-dir /data --reverse"
if [ -n "$ARCHIVE_URLS" ]; then
  CRON_CMD="$CRON_CMD --archiver-urls $ARCHIVE_URLS"
fi
if [ -n "$AUTH_TOKEN" ]; then
  CRON_CMD="$CRON_CMD --auth-token $AUTH_TOKEN"
fi

# Cron treats '%' as newline — escape them in the command string
CRON_CMD_ESCAPED="${CRON_CMD//%/\\%}"

# Use /etc/cron.d/ (requires username field; no user crontab to avoid double execution)
crontab -r 2>/dev/null || true
echo "$CRON_EXPRESSION root $CRON_CMD_ESCAPED >> $LOG_FILE 2>&1" > "$CRON_FILE"
echo "" >> "$CRON_FILE"  # trailing newline required by cron
chmod 0644 "$CRON_FILE"

echo "Cron job registered:"
cat "$CRON_FILE"

# --- Patch pscheduler limits (throughput duration 60 -> 300) ---
LIMITS_FILE="/etc/pscheduler/limits.conf"

if [ -f "$LIMITS_FILE" ]; then
  echo "Patching pscheduler limits.conf..."
  TMP_LIMITS=$(mktemp)

  if jq empty "$LIMITS_FILE" >/dev/null 2>&1; then
    jq '
      .limits |= map(
        if .name == "throughput-default-time"
        then
          .data.script |= map(
            if test("duration_as_seconds") and contains("60")
            then sub("60"; "300")
            else .
            end
          )
        else .
        end
      )
    ' "$LIMITS_FILE" > "$TMP_LIMITS"

    if jq empty "$TMP_LIMITS" >/dev/null 2>&1; then
      mv "$TMP_LIMITS" "$LIMITS_FILE"
      chmod 0644 "$LIMITS_FILE"
      echo "Updated throughput duration limit to 300s."
      # Restart pscheduler services to pick up new limits
      systemctl restart pscheduler-scheduler 2>/dev/null || true
      systemctl restart pscheduler-runner 2>/dev/null || true
    else
      echo "WARNING: Modified limits.conf is not valid JSON. Skipping patch."
      rm -f "$TMP_LIMITS"
    fi
  else
    echo "WARNING: $LIMITS_FILE is not valid JSON. Skipping patch."
  fi
else
  echo "limits.conf not found at $LIMITS_FILE. Skipping patch."
fi

# --- Start cron service ---
service cron start

echo "perfSONAR testpoint setup complete."
