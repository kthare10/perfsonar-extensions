#!/bin/bash

# Define cron schedule
CRON_SCHEDULE="${CRON_EXPRESSION:-*/5 * * * *}"
HOSTS="${HOSTS:-localhost}"
SCRIPT_PATH="/usr/src/app/periodic.py"
LOG_FILE="/data/pscheduler_cron.log"
PYTHON_BIN=$(which python3)

# Create the cron file
mkdir -p /etc/cron.d
CRON_FILE=/etc/cron.d/pscheduler_cron
echo "$CRON_SCHEDULE $PYTHON_BIN $SCRIPT_PATH --hosts $HOSTS >> $LOG_FILE 2>&1" > $CRON_FILE

# Apply permissions
chmod 0644 $CRON_FILE

# Register the cron file with crontab
crontab $CRON_FILE

# Start cron service in background
service cron start
