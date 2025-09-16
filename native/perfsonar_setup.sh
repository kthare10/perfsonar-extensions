#!/usr/bin/env bash
set -euo pipefail

# perfSONAR setup helper
# Usage:
#   ./perfsonar_setup.sh <SHIP_HOSTNAME> <SHIP_IP> <SHORE_HOSTNAME> <SHORE_IP>  [--remote REMOTE_IP] [--no-add-tests] [--interval <10M|2H|4H|6H>]
#
# Examples:
#   ./perfsonar_setup.sh ship-LOSA 23.134.233.34 shore-STAR 23.134.232.50 
#   ./perfsonar_setup.sh ship-LOSA 23.134.233.34 shore-STAR 23.134.232.50 --no-add-tests --interval 2H
#   ./perfsonar_setup.sh ship-LOSA 23.134.233.34 shore-STAR 23.134.232.50 --remote 23.134.232.50 --interval 10M

# ---------- args ----------
if [[ $# -lt 4 ]]; then
  echo "Usage: $0 <SHIP_HOSTNAME> <SHIP_IP> <SHORE_HOSTNAME> <SHORE_IP> [--remote REMOTE_IP] [--no-add-tests] [--interval <10M|2H|4H|6H>]" >&2
  exit 64
fi

SHIP_HOST="$1"
SHIP_IP="$2"
SHORE_HOST="$3"
SHORE_IP="$4"

shift 4

REMOTE_IP=""
NO_ADD_TESTS=false
SCHEDULE_INTERVAL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote)
      REMOTE_IP="$2"
      shift 2
      ;;
    --no-add-tests)
      NO_ADD_TESTS=true
      shift
      ;;
    --interval)
      if [[ $# -lt 2 ]]; then
        echo "Error: --interval requires an argument" >&2
        exit 65
      fi
      case "$2" in
        10M|2H|4H|6H)
          SCHEDULE_INTERVAL="$2"
          ;;
        *)
          echo "Error: Invalid interval '$2'. Allowed values: 10M, 2H, 4H, 6H" >&2
          exit 65
          ;;
      esac
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 65
      ;;
  esac
done

BASE_PSCONFIG="psconfig/base_psconfig.json"
OUT_PSCONFIG="psconfig/psconfig.json"

# ---------- helpers ----------
sudo_run() {
  if [[ $EUID -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

# Remove any existing /etc/hosts lines that contain the exact hostname as a token,
# then append the fresh "IP hostname" line.
update_hosts_entry() {
  local ip="$1" host="$2"
  local hosts_file="/etc/hosts"
  local tmp
  tmp="$(mktemp)"

  # Delete lines where the hostname appears as a whole token (begin/end or whitespace-delimited)
  # Use ERE (-E); keep a backup once.
  sudo_run sed -E "/(^|[[:space:]])${host}([[:space:]]|\$)/d" "$hosts_file" > "$tmp"
  sudo_run install -m 644 "$tmp" "$hosts_file"
  rm -f "$tmp"

  # Append the new mapping
  echo "${ip} ${host}" | sudo_run tee -a "$hosts_file" >/dev/null
}

# ---------- /etc/hosts ----------
echo "==> Updating /etc/hosts..."
update_hosts_entry "$SHORE_IP" "$SHORE_HOST"
update_hosts_entry "$SHIP_IP" "$SHIP_HOST"

# ---------- perfSONAR install ----------
echo "==> Installing perfSONAR..."
sudo_run bash scripts/perfsonar-install.sh

# ---------- allow logstash IPs ----------
echo "==> Allowing Logstash IPs..."
sudo_run bash scripts/allow_logstash_ips.sh "$SHORE_IP" "$SHIP_IP"

# ---------- build psconfig ----------
echo "==> Building psconfig..."
mkdir -p psconfig

CMD=( python3 psconfig/psconfig_builder.py
  --base_config_file "$BASE_PSCONFIG"
  --output_file "$OUT_PSCONFIG"
  --host_list "$SHIP_HOST" "$SHIP_IP" "$SHORE_HOST" "$SHORE_IP" 
)

if [[ -n "$REMOTE_IP" ]]; then
  echo "   Remote mode with --remote $REMOTE_IP"
  CMD+=( --remote "$REMOTE_IP" )
else
  echo "   Local mode"
  if $NO_ADD_TESTS; then
    CMD+=( --no_add_tests )
  fi
fi

if [[ -n "$SCHEDULE_INTERVAL" ]]; then
  echo "   Using schedule interval: $SCHEDULE_INTERVAL"
  CMD+=( --schedule_interval "$SCHEDULE_INTERVAL" )
fi

"${CMD[@]}"

# ---------- validate / publish / remote add ----------
echo "==> Validating psconfig..."
sudo_run psconfig validate "$OUT_PSCONFIG"

echo "==> Publishing psconfig..."
sudo_run psconfig publish "$OUT_PSCONFIG"

echo "==> Adding psconfig remote..."
sudo_run psconfig remote add "https://localhost/psconfig/psconfig.json" || \
  echo "Remote already added, skipping."

echo "Setup complete."

