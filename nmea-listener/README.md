# NMEA 0183 Navigation Data Listener

Captures NMEA 0183 navigation data broadcast via UDP from research vessel instrumentation (e.g., R/V Thompson) and archives it to the [pscheduler-result-archiver](https://github.com/kthare10/pscheduler-result-archiver) REST API. The archived navigation data can then be correlated with perfSONAR network measurements in Grafana dashboards — for example, to see whether throughput drops when roll/pitch increases or when heading changes.

## Supported NMEA Sentences

| Sentence | Source | Data |
|----------|--------|------|
| `$INGGA` | GPS receiver | Latitude, longitude, altitude, fix quality, satellites, HDOP |
| `$INHDT` | Gyrocompass | True heading |
| `$PSXN,20` | Kongsberg Seapath MRU | Quality/status indicators |
| `$PSXN,23` | Kongsberg Seapath MRU | Roll, pitch, heading, heave |

Data from all sentence types received at the same second are merged into a single `nav_data` row via the archiver's COALESCE-based upsert.

## Architecture

```
NMEA Instruments ──UDP broadcast──▶ nmea-listener container
                                        │
                                        │ POST /ps/measurements/nav
                                        │ (batched, bearer token auth)
                                        ▼
                                   Archiver REST API ──▶ TimescaleDB (nav_data table)
                                        │                        │
                                        │                        ▼
                                        │                   Grafana dashboards
                                        │                   (Nav Correlation)
                                        ▼
                                   Shore Archiver (optional remote)
```

## Quick Start

### 1. Configure

```bash
cp env.template .env
# Edit .env — at minimum set AUTH_TOKEN
```

### 2. Launch

```bash
docker compose -f docker-compose-nmea.yml up -d --build
```

### 3. Verify

```bash
docker logs -f nmea-listener
```

You should see log lines showing received sentences and periodic batch flushes.

## Configuration

All settings via environment variables in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `NMEA_UDP_PORT` | `13551` | UDP port to listen on (R/V Thompson uses 13551) |
| `ARCHIVE_URLS` | `https://localhost:8443/ps` | Comma-separated archiver REST API base URLs |
| `AUTH_TOKEN` | *(required)* | Bearer token for archiver authentication |
| `VESSEL_ID` | `rv-thompson` | Vessel identifier (partition key in `nav_data` table) |
| `BATCH_SIZE` | `50` | Number of nav data points to buffer before flushing |
| `FLUSH_INTERVAL_S` | `5.0` | Maximum seconds between flushes (even if buffer not full) |
| `VERIFY_TLS` | `false` | Verify TLS certificates when POSTing to archivers |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

## How It Works

1. **UDP reception** — Main thread binds to `NMEA_UDP_PORT` with `SO_BROADCAST` and receives datagrams.
2. **Parsing** — Standard sentences (`$INGGA`, `$INHDT`) are parsed with `pynmea2`. Proprietary `$PSXN` sentences are parsed manually (pynmea2 doesn't handle these).
3. **Buffering** — Parsed data points are accumulated in memory. A flush is triggered when the buffer reaches `BATCH_SIZE` or `FLUSH_INTERVAL_S` elapses.
4. **Archiving** — Batches are POSTed as JSON to all `ARCHIVE_URLS` with bearer token auth. This enables dual archiving (local + remote/shore).

## NMEA Simulator

For testing without real NMEA hardware, use the included simulator:

```bash
python3 nmea_sim.py [UDP_PORT] [DURATION_S]
python3 nmea_sim.py 13551 30
```

The simulator generates realistic GGA, HDT, PSXN,20, and PSXN,23 sentences at 1 Hz, simulating a vessel underway near Seattle with gentle rolling motion. No external dependencies — uses only the Python standard library.

## Docker Details

- **Base image**: `python-3.13-slim`
- **Network mode**: `host` (required to receive UDP broadcast packets)
- **Dependencies**: `pynmea2`, `requests`, `urllib3`
- **Runs as**: non-root user
- **Restart policy**: `unless-stopped`

## Deployment with setup_ship.sh

When deploying via [fabric-recipes](https://github.com/kthare10/fabric-recipes), the NMEA listener is automatically set up by passing `--nmea-port` to `setup_ship.sh`:

```bash
./setup_ship.sh --token "$TOKEN" \
  --hosts "10.0.0.1@shore" \
  --urls "https://localhost:8443/ps" \
  --nmea-port 13551 \
  --vessel-id rv-thompson
```

Omit `--nmea-port` to skip NMEA listener deployment entirely.

## Grafana Dashboard

The archiver repo includes a pre-provisioned **Navigation Correlation** dashboard (`provisioning/dashboards/nav-correlation-dashboard.json`) with panels for:

- Vessel position (geomap)
- Throughput vs. roll/pitch (dual Y-axis)
- RTT vs. heave
- Heading & GPS quality over time
- Motion detail (roll, pitch, heave)
- Loss vs. motion severity

The dashboard includes template variables for filtering by source/destination IP, traffic direction, and vessel ID.
