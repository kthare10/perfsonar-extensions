#!/bin/bash

# Read HOSTS and INTERVAL from environment variables
HOSTS="$HOSTS"
INTERVAL="$INTERVAL"

# Default interval if not provided
if [ -z "$INTERVAL" ]; then
  INTERVAL="0 */2 * * *"
  echo "No INTERVAL provided, defaulting to: $INTERVAL"
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

# Start crond in foreground
crond -n
