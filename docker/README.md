# perfSONAR Extensions — Docker

This directory contains Docker resources to:

* launch a **perfSONAR Testpoint** container,
* run a **periodic pScheduler runner** inside the container, and
* **archive results** to a REST service (e.g., `pscheduler-result-archiver`), which you can connect to **Grafana** for visualization (latency, throughput, RTT, MTU, trace).

## What’s included

```
docker/
├─ Dockerfile-perfsonar-testpoint      # Systemd-based testpoint image (for cron + runner)
├─ Dockerfile-perfsonar-tool           # Lightweight “direct tools” image (optional)
├─ docker-compose-testpoint.yml        # Compose stack for the testpoint + periodic runner
├─ docker-compose-tool.yml             # Compose stack to run tools directly (optional)
├─ pscheduler_test_runner.py           # Periodic runner (mounted into container)
├─ run_direct_tools.py                 # One-off tool runner (optional flow)
├─ entrypoint.sh                       # Helper for the tools image
├─ compose/
│  └─ bootstrap_cron.sh               # Installs crontab using CRON_EXPRESSION
├─ env.template                        # Copy to .env to customize
└─ scripts/                            # Helper scripts (if any)
```

## Requirements & notes

* **Linux host** recommended. `network_mode: host` is used in `docker-compose-testpoint.yml`. (Docker Desktop on macOS does not support host networking the same way.)
* An **archiver endpoint** reachable from the testpoint container (e.g., `http://archiver:8000` or `https://your-host/ps`).
* Optional **Grafana** can read from your archiver (JSON API or DB, depending on your archiver setup).

---

## Quick start (testpoint + periodic runner)

1. Clone and enter:

```bash
git clone https://github.com/kthare10/perfsonar-extensions.git
cd perfsonar-extensions/docker
```

2. Configure environment:

```bash
cp env.template .env
# Edit .env to set HOSTS, ARCHIVE_URLS, AUTH_TOKEN, CRON_EXPRESSION, etc.
```

3. Launch:

```bash
docker compose -f docker-compose-testpoint.yml up -d --build
docker compose -f docker-compose-testpoint.yml ps
```

4. Check logs:

```bash
docker logs -f perfsonar-testpoint
```

This starts a systemd-style container that bootstraps **cron** and runs `pscheduler_test_runner.py` on your schedule.

---

## Configuration

All key settings are exposed as environment variables in `docker-compose-testpoint.yml`. You can override them in `.env`.

```yaml
services:
  perfsonar-testpoint:
    environment:
      - HOSTS=${HOSTS:-23.134.232.50@shore-STAR}
      - AUTH_TOKEN=${AUTH_TOKEN:-changeme}
      - ARCHIVE_URLS=${ARCHIVE_URLS:-https://localhost:8443/ps}
      - TZ=${TZ:-UTC}
      - CRON_EXPRESSION=${CRON_EXPRESSION:-0 */2 * * *}
```

### Variables

* **`HOSTS`** — one or more destinations. Supports *IP + friendly name*:

  * `ip@name`  (recommended)
  * `name@ip`, `ip,name`, or `ip|name` also work
  * plain `host` is allowed (used for both ip and name)

  Examples:

  ```
  HOSTS='192.0.2.10@nyc-tp 198.51.100.20@lbnl-tp'
  HOSTS='perfsonar.example.org'
  HOSTS='[2001:db8::10]@ams-tp'
  ```

* **`ARCHIVE_URLS`** — one or more archiver base URLs (space or comma separated).
  Examples:

  ```
  ARCHIVE_URLS='http://archiver:8000'
  ARCHIVE_URLS='http://localhost:8000,https://archiver.example.org/ps'
  ```

* **`AUTH_TOKEN`** — bearer token sent to the archiver(s) if required (your runner also recognizes `AUTH_TOKEN`/`ARCHIVER_BEARER` internally).

* **`CRON_EXPRESSION`** — when to run the tests. Default `0 */2 * * *` = every 2 hours at minute 0.
  Examples:

  * every hour: `0 * * * *`
  * every 15 minutes: `*/15 * * * *`
  * daily at 03:00: `0 3 * * *`

* **`TZ`** — timezone for logs and cron.

### Volumes

```yaml
volumes:
  - ./pscheduler_test_runner.py:/usr/src/app/periodic.py
  - ./compose/bootstrap_cron.sh:/etc/cron.hourly/bootstrap_cron.sh
  - ./data_testpoint:/data
  - /sys/fs/cgroup:/sys/fs/cgroup:rw    # required for systemd in container
```

* Results & logs are written under `./data_testpoint` on the host.
* `periodic.py` is the mounted runner script invoked by cron.

---

## What the runner does

On each schedule:

1. Executes selected **pScheduler** tests to each entry in `HOSTS`.
2. Saves raw JSON into `/data` (host-mounted).
3. **POSTs** result JSON to each URL in `ARCHIVE_URLS` (REST ingest).
   This is designed for `pscheduler-result-archiver` (or a compatible REST service) that stores results for **Grafana**.

The runner supports categories like **latency**, **throughput**, **RTT**, **MTU**, and **trace**. It also supports the `ip@name` convention so Grafana panels can show human-friendly labels while keeping the destination IP for pScheduler itself.

---

## Optional: “direct tools” flow

If you want a lighter flow to run tools ad-hoc without the systemd/cron stack, use:

```bash
docker compose -f docker-compose-tool.yml up --build
```

The `run_direct_tools.py` script shows examples for invoking individual tools and can be adapted to push results to the same archiver.

---

## Verifying end-to-end

* **Testpoint container up**
  `docker ps | grep perfsonar-testpoint`

* **Cron installed**
  `docker exec -it perfsonar-testpoint bash -lc 'crontab -l'`

* **Runner logs/results**
  `ls -ltr data_testpoint/` (JSON files per category)
  `docker logs perfsonar-testpoint` (runner + cron bootstrap messages)

* **Archiver reachable**
  `curl -sS http://<archiver-host>:<port>/` (or the `/api/save` or health endpoint your archiver exposes)

* **Grafana**
  Add a JSON API (or DB) datasource pointing at your archiver and build panels for latency/throughput/RTT/MTU/trace.

---

## Tips & troubleshooting

* **Host networking (Linux)**: `network_mode: host` lets the container use host interfaces for tools like `owping`, `traceroute`, etc.
* **macOS**: host networking differs; for testing, you can still post to a remote archiver and run many tools, but some low-level networking behaviors differ from Linux.
* **TLS**: if your archiver is HTTPS with self-signed certs, either trust the CA in the container or configure the runner to skip verification (only for testing).
* **Reverse tests**: if you enable them in the runner, only certain categories support reverse (e.g., throughput, latency).

---

## Security

* Treat `AUTH_TOKEN` as sensitive; prefer injecting via `.env` or secrets managers.
* If exposing the archiver publicly, enforce TLS and authentication.
* Restrict who can schedule tests, especially throughput tests (`iperf3`) that can consume bandwidth.

---

## Updating

```bash
docker compose -f docker-compose-testpoint.yml pull
docker compose -f docker-compose-testpoint.yml build --no-cache
docker compose -f docker-compose-testpoint.yml up -d
```
