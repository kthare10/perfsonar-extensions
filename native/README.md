# perfSONAR Setup Helper

This repository provides a convenience script, `perfsonar_setup.sh`, to automate the setup of perfSONAR nodes (shore/central archive or ship/remote).  
It configures `/etc/hosts`, installs perfSONAR, applies Logstash access controls, generates a psconfig, and publishes it.

---

## Usage

```bash
./perfsonar_setup.sh <SHIP_HOSTNAME> <SHIP_IP> <SHORE_HOSTNAME> <SHORE_IP> [options]
````

### Required Arguments

* `<SHORE_HOSTNAME>` – Hostname for the shore/central archive node (e.g., `shore-STAR`).
* `<SHORE_IP>` – IP address for the shore node.
* `<SHIP_HOSTNAME>` – Hostname for the ship/remote node (e.g., `ship-LOSA`).
* `<SHIP_IP>` – IP address for the ship node.

### Options

* `--no-add-tests`
  Use this when configuring the **central archive/shore node**.
  It prevents tests from being added locally while still allowing validation, publishing, and remote registration.

* `--remote <REMOTE_IP>`
  Use this when configuring a **ship/remote node**.
  The psconfig will be generated with `--remote REMOTE_IP` so results are archived remotely (at the central archive).
  Pass central archive IP in `--remote`.

* `--interval <10M|2H|4H|6H>`
  Control the test scheduling interval passed to the psconfig builder (`--schedule_interval`).
  Valid values:

  * `10M` – Every 10 minutes
  * `2H` – Every 2 hours
  * `4H` – Every 4 hours
  * `6H` – Every 6 hours

---

## Examples

### Shore Node (Central Archive)

Run on the **shore node** with `--no-add-tests`:

```bash
./perfsonar_setup.sh shore-STAR 23.134.232.50 ship-LOSA 23.134.233.34 --no-add-tests
```

This:

* Updates `/etc/hosts`
* Installs perfSONAR
* Allows Logstash access
* Builds psconfig without tests (`--no_add_tests`)
* Validates, publishes, and registers the local psconfig

---

### Ship Node (Remote)

Run on the **ship node** with `--remote` and optionally control the interval:

```bash
./perfsonar_setup.sh ship-LOSA 23.134.233.34 shore-STAR 23.134.232.50 --remote 23.134.232.50 --interval 2H
```

This:

* Updates `/etc/hosts`
* Installs perfSONAR
* Allows Logstash access
* Builds psconfig with `--remote 23.134.232.50` so results are archived to the central node
* Configures tests to run every 2 hours
* Validates, publishes, and registers the local psconfig

---

## Cruise Data Offload (`archive_offload.sh`)

At the end of a cruise, use `archive_offload.sh` on the **shore/central archive node** to export results from OpenSearch/Elasticsearch as gzipped NDJSON.

### What it does

* Reads OpenSearch credentials from `/etc/perfsonar/opensearch/opensearch_login` **via `sudo`** by default (non-root friendly).
* Exports documents from the index (default: `pscheduler*`) for a given time window.
* Uses the Scroll API for large exports.
* Writes a `*.ndjson.gz` you can analyze or re-import later.

### Prerequisites

* `curl`, `jq`, `gzip`, and `date` available on the shore node.
* OpenSearch reachable at `https://localhost:9200` (default).
* The credentials file `/etc/perfsonar/opensearch/opensearch_login` should contain:

  ```
  <username> <password>
  ```

  (created by the archive setup; typically `admin <generatedpass>` or your own reader user).

### Usage

```bash
# Make executable
chmod +x archive_offload.sh
```

#### Last N days (recommended)

```bash
# Export last 10 days; reads creds via sudo from /etc/perfsonar/opensearch/opensearch_login
./archive_offload.sh --days 10 --insecure --outfile cruise_last10d.ndjson.gz
```

```bash
# Export last 30 days
./archive_offload.sh --days 30 --insecure --outfile cruise_last30d.ndjson.gz
```

#### Explicit time window (UTC ISO8601)

```bash
./archive_offload.sh \
  --from '2025-08-01T00:00:00Z' \
  --to   '2025-09-02T23:59:59Z' \
  --insecure \
  --outfile cruise_2025-08_to_2025-09-02.ndjson.gz
```

#### Override defaults (optional)

```bash
# Use a read-only user you created (instead of reading admin creds via sudo)
./archive_offload.sh \
  --days 14 \
  --user pscheduler_reader \
  --pass 'ReaderPass!' \
  --index pscheduler* \
  --outfile cruise_14d_reader.ndjson.gz
```

### Common flags

* `--days N` — export the last N days (mutually exclusive with `--from/--to`)
* `--from ISO` / `--to ISO` — explicit time window (UTC ISO8601)
* `--index NAME` — defaults to `pscheduler*` (use `logstash-*` if that’s your index pattern)
* `--time-field FIELD` — defaults to `@timestamp` (use `time-start` if that’s your mapping)
* `--outfile FILE` — output file name, defaults to `cruise_dump-YYYY-MM-DD.ndjson.gz`
* `--insecure` — ignore TLS validation (useful with self-signed certs)

### Verifying export

```bash
# Count docs
zcat cruise_last10d.ndjson.gz | wc -l

# Peek at first few
zcat cruise_last10d.ndjson.gz | head -n 3 | jq .
```

### Tip: convert NDJSON to CSV (example)

Once you decide the fields you need (e.g., `@timestamp`, `source`, `destination`, `throughput`), you can convert:

```bash
zcat cruise_last10d.ndjson.gz \
  | jq -r '[."@timestamp", .source, .destination, .throughput] | @csv' \
  > cruise_last10d.csv
```

---

## Notes

* The setup script expects the following to exist in your repo:

  * `scripts/perfsonar-install.sh`
  * `scripts/allow_logstash_ips.sh`
  * `psconfig/psconfig_builder.py`
  * `psconfig/base_psconfig.json`
* Requires `sudo` for modifying `/etc/hosts`, installing perfSONAR, and running `psconfig` commands.
* The setup script is idempotent: `/etc/hosts` entries are replaced if already present, not duplicated.

---

## Typical Workflow

1. **Run on the Shore/Central Archive Node:**

   ```bash
   ./perfsonar_setup.sh shore-STAR 23.134.232.50 ship-LOSA 23.134.233.34 --no-add-tests
   ```

2. **Run on the Ship/Remote Node(s):**

   ```bash
   ./perfsonar_setup.sh ship-LOSA 23.134.233.34 shore-STAR 23.134.232.50 --remote 23.134.232.50 --interval 4H
   ```

3. **End of Cruise — Offload Data (on Shore Node):**

   ```bash
   ./archive_offload.sh --days 30 --insecure --outfile cruise_last30d.ndjson.gz
   ```

This ensures the central archive is set up to manage configurations, ship nodes push results to shore at controlled intervals, and you can easily export the full dataset at the end of the cruise.
