#!/bin/bash

# Read HOSTS and INTERVAL from environment variables
HOSTS="$HOSTS"
INTERVAL="$INTERVAL"

# Default interval if not provided
if [ -z "$INTERVAL" ]; then
  INTERVAL="0 */2 * * *"
  echo "No INTERVAL provided, defaulting to: $INTERVAL (every 2 hours)"
fi

# Check if hosts provided
if [ -z "$HOSTS" ]; then
  echo "No hosts provided via HOSTS env variable! Exiting."
  exit 1
fi

echo "HOSTS received: $HOSTS"
echo "INTERVAL set to: $INTERVAL"

# Write cron job dynamically
echo "${INTERVAL} /usr/bin/python3 /usr/src/app/periodic.py --hosts ${HOSTS} --output-dir /data >> /data/cron.log 2>&1" > /etc/cron.d/daily-tests
chmod 0644 /etc/cron.d/daily-tests
crontab /etc/cron.d/daily-tests

echo "Cron job added for hosts: ${HOSTS} at interval: ${INTERVAL}"

# Detect OS and start cron daemon accordingly
OS_ID=$(grep "^ID=" /etc/os-release | cut -d'=' -f2 | tr -d '"')

echo "Detected OS: $OS_ID"

if [[ "$OS_ID" == "ubuntu" || "$OS_ID" == "debian" ]]; then
  echo "Starting cron in Ubuntu/Debian mode"
  cron -f
elif [[ "$OS_ID" == "rocky" || "$OS_ID" == "rhel" || "$OS_ID" == "centos" ]]; then
  echo "Starting crond in RHEL/Rocky mode"
  crond -n
else
  echo "Unknown OS: $OS_ID. Attempting to run crond."
  crond -n
fi

# Execute the original CMD (supervisord)
/usr/bin/supervisord -c /etc/supervisord.conf