# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**perfsonar-extensions** automates the deployment and operation of perfSONAR network performance testing, supporting two deployment models: Docker containers and native VM installation. The project manages periodic network tests (latency, throughput, traceroute, RTT, MTU, clock) between hosts and archives results to REST endpoints.

## Repository Structure

- **`docker/`** — Containerized deployment path
  - `pscheduler_test_runner.py` — Core test runner (~540 lines): executes pScheduler tests on a cron schedule, parses results, archives to REST endpoints
  - `run_direct_tools.py` — One-off test execution without cron
  - `docker-compose-testpoint.yml` — Primary stack (host networking, systemd-based)
  - `compose/bootstrap_cron.sh` — Container init: installs `archiver_client`, sets up crontab, patches pScheduler limits
  - `scripts/setup_env.py` — Generates `.env` files from template
- **`native/`** — Direct VM installation path
  - `perfsonar_setup.sh` — Main orchestrator: updates /etc/hosts, installs packages, generates psconfig
  - `psconfig/psconfig_builder.py` — Generates perfSONAR mesh config from `base_psconfig.json` template
  - `archive_offload.sh` — Exports results from OpenSearch/Elasticsearch via scroll API
- **`nmea-listener/`** — UDP listener for NMEA 0183 broadcasts (port 13551)
  - Parses `$xxGGA` (GPS, any talker ID), `$xxHDT` (heading, any talker ID), `$PASHR` (attitude/heading), `$PSXN,20` (MRU status), `$PSXN,23` (roll/pitch/heave)
  - Batches and POSTs parsed data to the archiver REST API with bearer token auth
  - `nmea_sim.py` — Simulator for testing without real NMEA hardware

## Architecture

### Two Deployment Models
1. **Docker (testpoint container)**: pScheduler runs inside a systemd container with cron-triggered `pscheduler_test_runner.py`. Configured entirely via environment variables (`HOSTS`, `AUTH_TOKEN`, `ARCHIVE_URLS`, `CRON_EXPRESSION`).
2. **Native (shore/ship pattern)**: `perfsonar_setup.sh` takes ship/shore hostnames+IPs. Shore nodes use `--no-add-tests` (archive only). Ship nodes use `--remote <SHORE_IP>` to push results upstream.

### Test Categories and Tools
| Category    | Tools                      |
|------------|----------------------------|
| latency    | owping, twping, halfping   |
| rtt        | ping, tcpping              |
| throughput | iperf3                     |
| trace      | traceroute, tracepath      |
| mtu        | fwmtu                      |
| clock      | psclock                    |

### Host Format Parsing
Hosts can be specified as: `ip@name`, `name@ip`, `ip,name`, `ip|name`, or plain `host`. The runner auto-detects which part is the IP vs. friendly name.

### NMEA Listener
Receives NMEA 0183 UDP broadcasts on a configurable port (default 13551), parses GPS position, heading, MRU status, and roll/pitch/heave sentences, then batches and POSTs them to the archiver REST API. Deployed via Docker with host networking to receive UDP broadcasts. Configured via env vars: `NMEA_UDP_PORT`, `ARCHIVE_URLS`, `AUTH_TOKEN`, `VESSEL_ID`, `BATCH_SIZE`, `FLUSH_INTERVAL_S`.

### Archiving Flow
Test results are saved as local JSON files and POSTed to REST archiver endpoints (bearer token auth, upsert mode). Multiple `ARCHIVE_URLS` are supported, separated by commas.

## Common Commands

### Docker deployment
```bash
cd docker
cp env.template .env   # then edit with real values
docker compose -f docker-compose-testpoint.yml up -d --build
docker logs -f perfsonar-testpoint
```

### Native deployment (ship node)
```bash
cd native
./perfsonar_setup.sh <SHIP_HOSTNAME> <SHIP_IP> <SHORE_HOSTNAME> <SHORE_IP> --remote <SHORE_IP> --interval 2H
```

### Native deployment (shore/archive node)
```bash
cd native
./perfsonar_setup.sh <SHORE_HOSTNAME> <SHORE_IP> <SHIP_HOSTNAME> <SHIP_IP> --no-add-tests
```

### NMEA listener deployment
```bash
cd nmea-listener
docker compose up -d --build       # uses host networking for UDP broadcast reception
python nmea_sim.py                  # run simulator for testing
```

### Export archived results
```bash
cd native
./archive_offload.sh --days 30 --insecure --outfile results.ndjson.gz
```

## Key Dependencies

- **Python**: `archiver_client==1.0.0` (custom REST archiver client), standard library only otherwise
- **System**: perfSONAR toolkit packages, Docker Engine + Compose (container path), jq, curl
- **Supported OS**: Ubuntu 20/22/24, Rocky 8/9

## Code Conventions

- Bash scripts use strict mode (`set -euo pipefail`)
- Python uses standard logging with dual output (file + console at separate levels)
- Setup scripts are idempotent (safe to re-run)
- No formal test suite or CI pipeline exists; verification is manual
