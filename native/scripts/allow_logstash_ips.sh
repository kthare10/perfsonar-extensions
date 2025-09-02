#!/usr/bin/env bash
# allow_logstash_ips.sh (rev2)
# Usage:
#   sudo ./allow_logstash_ips.sh 10.20.30.0/24 203.0.113.45
#   sudo ./allow_logstash_ips.sh               # just ensure localhost + RequireAny

set -euo pipefail

CONF="/etc/apache2/conf-available/apache-logstash.conf"
BACKUP_SUFFIX="$(date +%Y%m%d-%H%M%S)"
TMP="$(mktemp)"

if [[ ! -f "$CONF" ]]; then
  echo "ERROR: $CONF not found. Is the archive installed on this host?"
  exit 1
fi

echo "Backing up $CONF -> ${CONF}.bak.${BACKUP_SUFFIX}"
sudo cp -a "$CONF" "${CONF}.bak.${BACKUP_SUFFIX}"

# 1) Ensure a <RequireAny> block exists inside <Location "/logstash">, add localhost if absent.
#    NOTE: Use plain " instead of \" in regex; match optional quotes with the regex  "?  "
awk '
  BEGIN { inloc=0; haveReqAny=0 }
  /<Location[[:space:]]*"?\/logstash"?[[:space:]]*>/ { inloc=1; haveReqAny=0 }
  inloc && /<RequireAny>/ { haveReqAny=1 }
  inloc && /<\/Location>/ {
      if (!haveReqAny) {
          print "  <RequireAny>"
          print "    Require valid-user"
          print "    Require ip 127.0.0.1 ::1"
          print "  </RequireAny>"
      }
      inloc=0
  }
  { print }
' "$CONF" | sudo tee "$TMP" >/dev/null
sudo mv "$TMP" "$CONF"

# 2) Ensure the localhost line exists (handles files that already had <RequireAny> but no localhost)
if ! awk '
  BEGIN { inloc=0; haveLocal=0 }
  /<Location[[:space:]]*"?\/logstash"?[[:space:]]*>/ { inloc=1 }
  inloc && /<\/Location>/ { inloc=0 }
  inloc && /Require[[:space:]]+ip[[:space:]]+127\.0\.0\.1/ { haveLocal=1 }
  END { exit haveLocal?0:1 }
' "$CONF"; then
  sudo sed -i \
    '/<Location[[:space:]]*"*\/logstash"*[^>]*>/,/<\/Location>/{
       /<\/RequireAny>/ i\    Require ip 127.0.0.1 ::1
    }' "$CONF"
fi

# 3) Add any extra IPs/CIDRs passed on the CLI, only if missing
add_ip() {
  local ip="$1"
  # already present?
  if awk -v ip="$ip" '
    BEGIN { inloc=0; found=0 }
    /<Location[[:space:]]*"?\/logstash"?[[:space:]]*>/ { inloc=1 }
    inloc && /<\/Location>/ { inloc=0 }
    inloc && $0 ~ ("Require[[:space:]]+ip[[:space:]]+" ip "([[:space:]]|$)") { found=1 }
    END { exit found?0:1 }
  ' "$CONF"; then
    echo "Already present: Require ip $ip"
  else
    echo "Adding: Require ip $ip"
    sudo sed -i \
      '/<Location[[:space:]]*"*\/logstash"*[^>]*>/,/<\/Location>/{
         /<\/RequireAny>/ i\    Require ip '"$ip"'
      }' "$CONF"
  fi
}

if (( $# > 0 )); then
  for ip in "$@"; do
    add_ip "$ip"
  done
fi

echo "Validating Apache config..."
sudo apachectl -t
echo "Reloading Apache..."
sudo systemctl reload apache2
echo "Done. Updated $CONF"
