#!/bin/bash

# Define cron schedule
CRON_SCHEDULE="${CRON_EXPRESSION:-*/5 * * * *}"
HOSTS="${HOSTS:-localhost}"
ARCHIVE="${ARCHIVE:-/usr/src/app/config.json}"
URL="${URL:-localhost}"
SCRIPT_PATH="/usr/src/app/periodic.py"
LOG_FILE="/data/pscheduler_cron.log"
PYTHON_BIN=$(which python3)

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
