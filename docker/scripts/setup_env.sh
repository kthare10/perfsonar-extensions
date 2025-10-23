#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./setup_env.sh /path/to/.env AUTH_TOKEN \
#       [HOSTS="23.134.232.50@shore-STAR"] \
#       [ARCHIVE_URLS="https://localhost:8443/ps,https://23.134.232.50:8443/ps"] \
#       [TZ="UTC"] \
#       [CRON_EXPRESSION="0 */2 * * *"]
#
# Example:
#   ./setup_env.sh pscheduler-result-archiver/.env "$ARCHIVER_TOKEN"

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 /path/to/.env AUTH_TOKEN [HOSTS] [ARCHIVE_URLS] [TZ] [CRON_EXPRESSION]" >&2
  exit 1
fi

ENV_PATH="$1"
AUTH_TOKEN="$2"
HOSTS="${3:-23.134.232.50@shore-STAR}"
ARCHIVE_URLS="${4:-https://localhost:8443/ps,https://23.134.232.50:8443/ps}"
TZ_VAL="${5:-UTC}"
CRON_EXPR="${6:-0 */2 * * *}"

mkdir -p "$(dirname "$ENV_PATH")"
touch "$ENV_PATH"
cp -a "$ENV_PATH" "${ENV_PATH}.bak.$(date +%s)"

# Safely add or replace KEY=VALUE lines in .env (no quotes; values may contain spaces)
update_kv () {
  local key="$1"
  local val="$2"
  # Escape sed-sensitive chars in key; escape & and \ in value
  local key_re
  key_re="$(printf '%s' "$key" | sed -e 's/[.[\*^$]/\\&/g')"
  local val_esc
  val_esc="$(printf '%s' "$val" | sed -e 's/[&\\/]/\\&/g')"

  if grep -Eq "^[[:space:]]*${key_re}=" "$ENV_PATH"; then
    # Replace existing
    sed -E -i "s|^[[:space:]]*${key_re}=.*$|${key}=${val_esc}|" "$ENV_PATH"
  else
    # Append
    printf '%s=%s\n' "$key" "$val" >> "$ENV_PATH"
  fi
}

update_kv "HOSTS" "$HOSTS"
update_kv "AUTH_TOKEN" "$AUTH_TOKEN"
update_kv "ARCHIVE_URLS" "$ARCHIVE_URLS"
update_kv "TZ" "$TZ_VAL"
update_kv "CRON_EXPRESSION" "$CRON_EXPR"

echo "Wrote $(realpath "$ENV_PATH")"
