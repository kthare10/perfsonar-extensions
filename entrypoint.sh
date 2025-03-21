#!/bin/bash

# Read HOSTS from environment variable
HOSTS="$HOSTS"

# Check if hosts provided
if [ -z "$HOSTS" ]; then
  echo "No hosts provided via HOSTS env variable! Exiting."
  exit 1
fi

echo "HOSTS received: $HOSTS"

# Write cron job dynamically
echo "*/30 * * * * /usr/bin/python3 /usr/src/app/run_direct_tools.py --hosts ${HOSTS} --output-dir /data >> /data/cron.log 2>&1" > /etc/cron.d/daily-tests
chmod 0644 /etc/cron.d/daily-tests
crontab /etc/cron.d/daily-tests

echo "Cron job added for hosts: ${HOSTS}"

# Start crond in foreground
crond -n

