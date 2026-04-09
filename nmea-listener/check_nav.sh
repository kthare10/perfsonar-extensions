#!/usr/bin/env bash
# Query the archiver's nav data endpoint from the command line.
#
# Usage:
#   ./check_nav.sh                          # latest 10 points
#   ./check_nav.sh -n 50                    # latest 50 points
#   ./check_nav.sh -v rv-thompson           # filter by vessel
#   ./check_nav.sh -s 2026-04-09T00:00:00Z # points after start time
#   ./check_nav.sh -e 2026-04-09T12:00:00Z # points before end time
#   ./check_nav.sh -u https://23.134.232.51:8443/ps  # custom archiver URL
#   ./check_nav.sh -r                       # raw JSON (no formatting)
#
# Requires: curl, jq (optional, for pretty output)

set -euo pipefail

# Defaults
URL="${ARCHIVE_URL:-https://localhost:8443/ps}"
TOKEN="${AUTH_TOKEN:-}"
LIMIT=10
VESSEL=""
START=""
END=""
RAW=false
VERIFY=""

usage() {
    sed -n '2,11p' "$0" | sed 's/^# \?//'
    exit 0
}

while getopts "u:t:n:v:s:e:rkh" opt; do
    case $opt in
        u) URL="$OPTARG" ;;
        t) TOKEN="$OPTARG" ;;
        n) LIMIT="$OPTARG" ;;
        v) VESSEL="$OPTARG" ;;
        s) START="$OPTARG" ;;
        e) END="$OPTARG" ;;
        r) RAW=true ;;
        k) VERIFY="-k" ;;
        h) usage ;;
        *) usage ;;
    esac
done

# Build query string
QS="limit=${LIMIT}"
[ -n "$VESSEL" ] && QS="${QS}&vessel_id=${VESSEL}"
[ -n "$START" ]  && QS="${QS}&start=${START}"
[ -n "$END" ]    && QS="${QS}&end=${END}"

ENDPOINT="${URL%/}/nav?${QS}"

# Build curl args
CURL_ARGS=(-s ${VERIFY:--k})
[ -n "$TOKEN" ] && CURL_ARGS+=(-H "Authorization: Bearer ${TOKEN}")
CURL_ARGS+=(-H "Accept: application/json")

RESPONSE=$(curl "${CURL_ARGS[@]}" "$ENDPOINT")

if [ "$RAW" = true ]; then
    echo "$RESPONSE"
    exit 0
fi

# Try jq for nice output, fall back to python, then raw
if command -v jq &>/dev/null; then
    SIZE=$(echo "$RESPONSE" | jq -r '.size // 0')
    echo "=== Nav Data: ${SIZE} points ==="
    echo ""
    echo "$RESPONSE" | jq -r '
        .data[]? |
        "\(.ts)  lat=\(.latitude // "n/a")  lon=\(.longitude // "n/a")  " +
        "hdg=\(.heading_true // "n/a")  roll=\(.roll_deg // "n/a")  " +
        "pitch=\(.pitch_deg // "n/a")  heave=\(.heave_m // "n/a")  " +
        "fix=\(.fix_quality // "n/a")  sats=\(.num_satellites // "n/a")"'
    echo ""
    echo "--- Full JSON (first 3) ---"
    echo "$RESPONSE" | jq '.data[:3]'
elif command -v python3 &>/dev/null; then
    echo "$RESPONSE" | python3 -m json.tool
else
    echo "$RESPONSE"
fi
