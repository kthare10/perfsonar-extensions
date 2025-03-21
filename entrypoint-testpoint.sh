#!/bin/bash
set -e

echo "Running custom environment setup..."

# Export env vars for systemd & cron (optional)
printenv | grep -E '^(HOSTS|INTERVAL|TZ)=' > /etc/container-environment

# Optionally start/enable any systemd service you need
systemctl daemon-reload
systemctl enable custom-cron.service

echo "Custom setup complete."

# Execute the original CMD (supervisord)
/usr/bin/supervisord -c /etc/supervisord.conf
