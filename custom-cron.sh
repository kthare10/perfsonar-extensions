#!/bin/bash

echo "Exporting environment variables to /etc/environment"

printenv | grep -E '^(HOSTS|INTERVAL|TZ)=' >> /etc/environment
source /etc/environment

echo "HOSTS: ${HOSTS}"
echo "INTERVAL: ${INTERVAL:-0 */2 * * *}"

if [ -z "$HOSTS" ]; then
  echo "No hosts provided! Exiting."
  exit 1
fi

echo "${INTERVAL} /usr/bin/python3 /usr/src/app/periodic.py --hosts ${HOSTS} --output-dir /data >> /data/cron.log 2>&1" > /etc/cron.d/daily-tests
chmod 0644 /etc/cron.d/daily-tests
crontab /etc/cron.d/daily-tests

echo "Cron job added for hosts: ${HOSTS} at interval: ${INTERVAL}"

/usr/sbin/cron -f
