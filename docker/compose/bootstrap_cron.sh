#!/bin/bash

# Define cron schedule
CRON_SCHEDULE="${CRON_EXPRESSION:-0 */2 * * *}"
CRON_SCHEDULE="0 */6 * * *"
HOSTS="${HOSTS:-localhost}"
ARCHIVE="${ARCHIVE:-/usr/src/app/config.json}"
URL="${URL:-localhost}"
SCRIPT_PATH="/usr/src/app/periodic.py"
LOG_FILE="/data/pscheduler_cron.log"
PYTHON_BIN=$(which python3)

# --- Step 2: Reset Cron Entries ---
echo "Cleaning existing crontab..."
crontab -r 2>/dev/null

# Create the cron file
mkdir -p /etc/cron.d
CRON_FILE=/etc/cron.d/pscheduler_cron
echo "$CRON_SCHEDULE $PYTHON_BIN $SCRIPT_PATH --hosts $HOSTS --output-dir /data --archive $ARCHIVE --url $URL >> $LOG_FILE 2>&1" > $CRON_FILE

# Apply permissions
chmod 0644 $CRON_FILE

# Register the cron file with crontab
crontab $CRON_FILE

# Start cron service in background
service cron start

# Read env variables or use defaults
AUTH_TOKEN=${BEARER_TOKEN:-"Basic cGVyZnNvbmFyOjc0V0daZjRvcm9TdGZlUGx1WGVm"}
ARCHIVER_IP=${HOST_IP:-"127.0.0.1"}

# Write dynamic archiver config
cat > $ARCHIVE <<EOF
{
  "archiver": "http",
  "data": {
    "schema": 3,
    "_url": "https://${ARCHIVER_IP}/logstash",
    "verify-ssl": false,
    "op": "put",
    "_headers": {
      "x-ps-observer": "{% scheduled_by_address %}",
      "content-type": "application/json",
      "Authorization": "${AUTH_TOKEN}"
    }
  }
}
EOF

# --- (Optional) Step 6: Patch pscheduler limits if root ---
# Only run if pscheduler limits file exists
LIMITS_FILE="/etc/pscheduler/limits.conf"
TMP_LIMITS=$(mktemp)

echo "Checking and patching pscheduler limits.conf..."

if [ -f "$LIMITS_FILE" ]; then

  # Check if the file is valid JSON before proceeding
  if jq empty "$LIMITS_FILE" >/dev/null 2>&1; then
    echo "Valid JSON detected in $LIMITS_FILE"

    jq '
      # Update the throughput-default-time rule
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

    # Validate the modified file
    if jq empty "$TMP_LIMITS" >/dev/null 2>&1; then
      mv "$TMP_LIMITS" "$LIMITS_FILE"
      chmod 0644 "$LIMITS_FILE"
      echo "Successfully updated throughput duration limit to 300s."
    else
      echo "Error: Modified limits.conf is not valid JSON. Aborting patch."
      rm -f "$TMP_LIMITS"
    fi

  else
    echo "Error: Existing $LIMITS_FILE is not valid JSON. Manual inspection required."
  fi

  # Restart pscheduler services if available
  systemctl restart pscheduler-scheduler 2>/dev/null || service pscheduler-scheduler restart
  systemctl restart pscheduler-runner 2>/dev/null || service pscheduler-runner restart

else
  echo "limits.conf not found at $LIMITS_FILE. Skipping patch."
fi

echo "Adding Ookla repository for Speedtest CLI..."
curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash

echo "Installing Speedtest CLI..."
sudo apt-get install -y speedtest

echo "Speedtest CLI installation complete."