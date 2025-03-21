#!/bin/bash

echo "Setting up cron job..."

HOSTS="${HOSTS}"
INTERVAL="${INTERVAL:-0 */2 * * *}"

if [ -z "$HOSTS" ]; then
  echo "No HOSTS provided! Exiting."
  exit 1
fi

echo "Using HOSTS: ${HOSTS}"
echo "Using INTERVAL: ${INTERVAL}"

echo "${INTERVAL} /usr/bin/python3 /usr/src/app/periodic.py --hosts ${HOSTS} --output-dir /data >> /data/cron.log 2>&1" > /etc/cron.d/daily-tests
chmod 0644 /etc/cron.d/daily-tests
crontab /etc/cron.d/daily-tests

echo "Cron job added."

# Restart cron daemon
service cron restart
