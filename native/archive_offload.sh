#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------------------
# archive_offload.sh
#   Dump perfSONAR results from OpenSearch/Elasticsearch on the SHORE node.
#
#   - Uses scroll API to export large datasets.
#   - Exports as gzipped NDJSON (one JSON doc per line).
#   - Reads default credentials from /etc/perfsonar/opensearch/opensearch_login
#     via sudo (so it works for non-root users) unless --user/--pass are supplied.
#   - Accepts --days N for "last N days" window; or --from/--to for explicit range.
#
# Usage (examples):
#   # Last 10 days (auto-read creds with sudo):
#   ./archive_offload.sh --days 10 --insecure --outfile cruise_10d.ndjson.gz
#
#   # Explicit window:
#   ./archive_offload.sh --from '2025-08-01T00:00:00Z' --to '2025-09-02T23:59:59Z'
#
#   # Override user/pass:
#   ./archive_offload.sh --days 30 --user pscheduler_reader --pass 'ReaderPass!'
#
# Notes:
#   * Default host: https://localhost:9200
#   * Default index: pscheduler*
#   * Default time field: @timestamp
#   * Requires: curl, jq, gzip, date (GNU date recommended)
# ------------------------------------------------------------------------------

HOST="https://localhost:9200"
INDEX="pscheduler*"
USER=""
PASS=""
FROM=""
TO=""
DAYS=""
TIME_FIELD="@timestamp"
SIZE=1000
OUTFILE="cruise_dump-$(date +%F).ndjson.gz"
CURL_INSECURE=()

die() { echo "ERROR: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)       HOST="$2"; shift 2;;
    --index)      INDEX="$2"; shift 2;;
    --user)       USER="$2"; shift 2;;
    --pass)       PASS="$2"; shift 2;;
    --from)       FROM="$2"; shift 2;;
    --to)         TO="$2"; shift 2;;
    --days)       DAYS="$2"; shift 2;;
    --time-field) TIME_FIELD="$2"; shift 2;;
    --size)       SIZE="$2"; shift 2;;
    --outfile)    OUTFILE="$2"; shift 2;;
    --insecure)   CURL_INSECURE=(--insecure); shift;;
    -h|--help)    sed -n '1,120p' "$0"; exit 0;;
    *)            die "Unknown argument: $1";;
  esac
done

need curl
need jq
need gzip
need date

# Compute FROM/TO if --days was supplied
if [[ -n "$DAYS" ]]; then
  [[ -z "$FROM" && -z "$TO" ]] || die "Use either --days N OR --from/--to, not both."
  [[ "$DAYS" =~ ^[0-9]+$ ]] || die "--days must be a positive integer"
  # UTC ISO-8601
  TO="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  # GNU date syntax; if unavailable, adjust for your shell/OS
  FROM="$(date -u -d "$DAYS days ago" +"%Y-%m-%dT%H:%M:%SZ")"
fi

# Require a window
if [[ -z "$FROM" || -z "$TO" ]]; then
  die "You must provide a time window via --days N or --from ISO --to ISO"
fi

# Read creds from opensearch_login via sudo if not explicitly provided
if [[ -z "$USER" || -z "$PASS" ]]; then
  if sudo test -r /etc/perfsonar/opensearch/opensearch_login; then
    # shellcheck disable=SC2046
    read -r USER PASS < <(sudo awk 'NR==1 {print $1, $2}' /etc/perfsonar/opensearch/opensearch_login)
    [[ -n "$USER" && -n "$PASS" ]] || die "Credentials file is malformed."
    echo "==> Using credentials from /etc/perfsonar/opensearch/opensearch_login (user: $USER)"
  else
    die "No --user/--pass provided and cannot read /etc/perfsonar/opensearch/opensearch_login (need sudo)."
  fi
fi

TMPDIR="$(mktemp -d)"
SCROLL_FILE="$TMPDIR/scroll.json"
RESULTS_FILE="$TMPDIR/results.ndjson"
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT

echo "==> Exporting from $HOST index '$INDEX'"
echo "    Time range: $FROM  ->  $TO  (field: $TIME_FIELD)"
echo "    Batch size: $SIZE"
echo "    Output:     $OUTFILE"

# Initial search with scroll
echo "==> Starting initial scroll search..."
curl -sS "${CURL_INSECURE[@]}" -u "$USER:$PASS" \
  -H 'Content-Type: application/json' \
  -X POST "$HOST/$INDEX/_search?scroll=2m" \
  -d @- > "$SCROLL_FILE" <<JSON
{
  "size": $SIZE,
  "_source": true,
  "query": {
    "range": {
      "$TIME_FIELD": {
        "gte": "$FROM",
        "lte": "$TO",
        "format": "strict_date_optional_time"
      }
    }
  },
  "sort": [
    { "$TIME_FIELD": "asc" },
    { "_id": "asc" }
  ]
}
JSON

SCROLL_ID=$(jq -r '._scroll_id // empty' "$SCROLL_FILE")
[[ -n "$SCROLL_ID" ]] || { echo "Response:" >&2; cat "$SCROLL_FILE" >&2; die "Scroll init failed (index, creds, or time field?)"; }

jq -c '.hits.hits[] | ._source' "$SCROLL_FILE" >> "$RESULTS_FILE"

TOTAL=$(jq -r '.hits.total.value // .hits.total // 0' "$SCROLL_FILE")
GOT_FIRST=$(jq -r '.hits.hits | length' "$SCROLL_FILE")
echo "==> Total reported by ES: $TOTAL; got $GOT_FIRST in first page."

# Iterate scroll
PAGE=$GOT_FIRST
while :; do
  curl -sS "${CURL_INSECURE[@]}" -u "$USER:$PASS" \
    -H 'Content-Type: application/json' \
    -X POST "$HOST/_search/scroll" \
    -d @- > "$SCROLL_FILE" <<JSON
{
  "scroll": "2m",
  "scroll_id": "$SCROLL_ID"
}
JSON

  COUNT=$(jq -r '.hits.hits | length' "$SCROLL_FILE")
  [[ "$COUNT" =~ ^[0-9]+$ ]] || { echo "Unexpected response:" >&2; cat "$SCROLL_FILE" >&2; break; }
  [[ "$COUNT" -gt 0 ]] || break

  jq -c '.hits.hits[] | ._source' "$SCROLL_FILE" >> "$RESULTS_FILE"
  PAGE=$(( PAGE + COUNT ))
  echo "   … fetched $COUNT (cumulative $PAGE)"
  SCROLL_ID=$(jq -r '._scroll_id // empty' "$SCROLL_FILE")
  [[ -n "$SCROLL_ID" ]] || break
done

# Best-effort clear scroll
if [[ -n "${SCROLL_ID:-}" ]]; then
  curl -sS "${CURL_INSECURE[@]}" -u "$USER:$PASS" \
    -H 'Content-Type: application/json' \
    -X DELETE "$HOST/_search/scroll" \
    -d "{\"scroll_id\": [\"$SCROLL_ID\"]}" >/dev/null || true
fi

LINES=$(wc -l < "$RESULTS_FILE" || echo 0)
echo "==> Writing $LINES documents to $OUTFILE (gzipped NDJSON)…"
gzip -c "$RESULTS_FILE" > "$OUTFILE"

echo "==> Done."
echo "    Inspect a few rows: zcat $OUTFILE | head -n 3 | jq '.'"
