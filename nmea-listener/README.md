# NMEA 0183 Navigation Data Listener

Captures NMEA 0183 navigation data broadcast via UDP from research vessel instrumentation (e.g., R/V Thompson) and archives it to the [pscheduler-result-archiver](https://github.com/kthare10/pscheduler-result-archiver) REST API. The archived navigation data can then be correlated with perfSONAR network measurements in Grafana dashboards — for example, to see whether throughput drops when roll/pitch increases or when heading changes.

## Supported NMEA Sentences

| Sentence | Talker IDs | Source | Data |
|----------|-----------|--------|------|
| `$xxGGA` | GP, GN, IN, GL, GA, etc. | GPS/GNSS receiver | Latitude, longitude, altitude, fix quality, satellites, HDOP |
| `$xxHDT` | HE, IN, GP, GN, HC, etc. | Gyrocompass / heading sensor | True heading |
| `$PASHR` | — (proprietary) | Hemisphere/Ashtech IMU | Heading, roll, pitch, heave |
| `$PSXN,20` | — (proprietary) | Kongsberg Seapath MRU | Quality/status indicators |
| `$PSXN,23` | — (proprietary) | Kongsberg Seapath MRU | Roll, pitch, heading, heave |

Any standard NMEA talker ID is accepted for GGA and HDT sentences (e.g., `$GNGGA`, `$GPGGA`, `$HEHDT`).

Data from all sentence types received at the same second are merged into a single `nav_data` row via the archiver's COALESCE-based upsert.

## Architecture

```
NMEA Instruments ──UDP broadcast──▶ nmea-listener container
                                        │
                                        ├─── POST /ps/measurements/nav ──▶ Local Archiver (every 5 min)
                                        │    (batched, bearer token auth)       │
                                        │                                       ▼
                                        │                                  TimescaleDB ──▶ Grafana
                                        │
                                        └─── POST /ps/measurements/nav ──▶ Shore Archiver (every 6 hrs)
                                             (chunked ≤1000 pts/request,        │
                                              conserves satellite BW)           ▼
                                                                           TimescaleDB ──▶ Grafana
```

Each archive destination has its own buffer and flush timer, allowing frequent local archiving while conserving satellite bandwidth on remote links.

## Quick Start

### 1. Configure

```bash
cp env.template .env
# Edit .env — at minimum set AUTH_TOKEN and ARCHIVE_URLS
```

### 2. Launch

```bash
docker compose -f docker-compose-nmea.yml up -d --build
```

### 3. Verify

```bash
docker logs -f nmea-listener
```

You should see log lines showing periodic batch flushes. Set `LOG_LEVEL=DEBUG` in `.env` to see individual parsed sentences.

### 4. Query archived data (no browser needed)

```bash
./check_nav.sh                                          # latest 10 points from local archiver
./check_nav.sh -u https://23.134.232.51:8443/ps -n 50  # from remote archiver
./check_nav.sh -v rv-thompson -s 2026-04-09T00:00:00Z   # filter by vessel & time
```

## Configuration

All settings via environment variables in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `NMEA_UDP_PORT` | `13551` | UDP port to listen on (R/V Thompson uses 13551) |
| `ARCHIVE_URLS` | `https://localhost:8443/ps` | Comma-separated archiver URLs (see [Per-URL intervals](#per-url-flush-intervals)) |
| `AUTH_TOKEN` | *(required)* | Bearer token for archiver authentication |
| `VESSEL_ID` | `rv-thompson` | Vessel identifier (partition key in `nav_data` table) |
| `BATCH_SIZE` | `65000` | Max points per destination buffer before forcing early flush |
| `FLUSH_INTERVAL_S` | `300` | Flush interval for local URLs (localhost/127.0.0.1), in seconds |
| `REMOTE_FLUSH_INTERVAL_S` | `21600` | Flush interval for remote URLs, in seconds (default 6 hours) |
| `VERIFY_TLS` | `false` | Verify TLS certificates when POSTing to archivers |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

### Per-URL Flush Intervals

Each archive URL can have its own flush interval, configured in three ways:

**1. Automatic (default)** — URLs containing `localhost` or `127.0.0.1` use `FLUSH_INTERVAL_S`, all others use `REMOTE_FLUSH_INTERVAL_S`:

```bash
ARCHIVE_URLS=https://localhost:8443/ps,https://23.134.232.51:8443/ps
FLUSH_INTERVAL_S=300          # local: every 5 min
REMOTE_FLUSH_INTERVAL_S=21600 # remote: every 6 hours
```

**2. Per-URL override** — Append `@<seconds>` to any URL for explicit control:

```bash
ARCHIVE_URLS=https://localhost:8443/ps@300,https://23.134.232.51:8443/ps@14400
# local: every 5 min, remote: every 4 hours
```

**3. Mixed** — Combine automatic detection with overrides:

```bash
ARCHIVE_URLS=https://localhost:8443/ps,https://remote-a:8443/ps@3600,https://remote-b:8443/ps@21600
# local: uses FLUSH_INTERVAL_S, remote-a: 1 hour, remote-b: 6 hours
```

### Buffer Size and Chunking

At ~3 NMEA sentences per second, the approximate buffer sizes for common intervals:

| Interval | Points buffered | Memory |
|----------|----------------|--------|
| 5 min | ~900 | <1 MB |
| 1 hour | ~10,800 | ~5 MB |
| 4 hours | ~43,200 | ~20 MB |
| 6 hours | ~64,800 | ~30 MB |

The archiver API accepts max 1000 points per request. Large flushes are automatically chunked into multiple 1000-point requests. `BATCH_SIZE` acts as a memory safety cap — if a destination's buffer reaches this limit before the timer fires, it triggers an early flush.

## How It Works

1. **UDP reception** — Main thread binds to `NMEA_UDP_PORT` with `SO_BROADCAST` and receives datagrams. Requires Docker `network_mode: host`.
2. **Parsing** — Standard sentences (`$xxGGA`, `$xxHDT`) are parsed with `pynmea2` (any talker ID). Proprietary sentences (`$PASHR`, `$PSXN`) are parsed manually.
3. **Buffering** — Each archive destination has an independent buffer. Parsed points are appended to all destination buffers.
4. **Deduplication** — Before flushing, points with the same `(ts, vessel_id)` are merged (non-null values win, `aux` JSONB objects combined).
5. **Flushing** — Each destination has its own timer thread. When the timer fires, the buffer is drained, chunked into ≤1000-point batches, and POSTed with bearer token auth.

## CLI Query Tool

`check_nav.sh` queries the archiver's GET `/ps/nav` endpoint from the command line:

```bash
./check_nav.sh -h                    # show usage
./check_nav.sh                       # latest 10 points (local archiver)
./check_nav.sh -n 50                 # latest 50 points
./check_nav.sh -v rv-thompson        # filter by vessel
./check_nav.sh -s 2026-04-09T00:00:00Z -e 2026-04-09T12:00:00Z  # time range
./check_nav.sh -u https://23.134.232.51:8443/ps  # query remote archiver
./check_nav.sh -r                    # raw JSON output
```

Reads `ARCHIVE_URL` and `AUTH_TOKEN` from the environment if set. Requires `curl`; uses `jq` for pretty output if available.

## NMEA Simulator

For testing without real NMEA hardware, use the included simulator:

```bash
python3 nmea_sim.py [UDP_PORT] [DURATION_S]
python3 nmea_sim.py 13551 30
```

The simulator generates realistic GGA, HDT, PSXN,20, and PSXN,23 sentences at 1 Hz, simulating a vessel underway near Seattle with gentle rolling motion. No external dependencies — uses only the Python standard library.

## Docker Details

- **Base image**: `python:3.13-slim`
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
