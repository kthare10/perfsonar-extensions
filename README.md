# perfsonar-extensions

A set of PerfSONAR container extensions designed to automate periodic network performance monitoring tests across a defined set of hosts.

## Table of Contents

- [Overview](#overview)
- [Components](#components)
  - [perfsonar-testpoint](#perfsonar-testpoint)
  - [perfsonar-tool](#perfsonar-tool)
- [Supported Tests](#supported-tests)
- [Setup](#setup)
- [Usage](#usage)
- [Directory Structure](#directory-structure)
- [Areas for Improvement](#areas-for-improvement)

---

## Overview

This project extends standard PerfSONAR containers to facilitate automated, periodic network testing. It supports various performance tests such as latency, throughput, RTT, MTU discovery, path tracing, and jitter measurements across multiple hosts.

---

## Components

### 1. **perfsonar-testpoint**

Builds upon the official [perfsonar-testpoint-docker](https://github.com/perfsonar/perfsonar-testpoint-docker) container with the following enhancements:

- Adds a Python script to automate periodic network tests.
- Reads target hosts from the `HOSTS` environment variable defined in `docker-compose.yml`.
- Mounts configuration and log directories for persistence.
- Uses `systemd` and appropriate `cgroup` settings for test compatibility.

**Launch:**
```bash
docker-compose up -d perfsonar-testpoint
```

---

### 2. **perfsonar-tool**

A lightweight container based on `rocky:9` that installs PerfSONAR command-line tools and runs periodic network tests on specified hosts.

**Launch:**
```bash
docker-compose up -d perfsonar-tool
```

---

## Supported Tests

The following network tests are supported and scheduled periodically:

| Test Type      | Tools Used                                                                |
|----------------|-------------------------------------------------------------------------|
| **Latency**    | `owping`, `twping`, `halfping`                                           |
| **RTT**        | `ping`, `tcpping`, `twping`                                              |
| **Throughput** | `iperf3`, `nuttcp`, `ethr`                                               |
| **MTU**        | `fwmtu`                                                                  |
| **Path Trace** | `traceroute`, `paris-traceroute`, `tracepath`                            |
| **Jitter**     | Captured using `owping`, `twping`, `iperf3`                              |

---

## Setup

### Prerequisites:

- Docker & Docker Compose installed.
- Necessary network permissions (for `host` mode and required ports).
  
### Clone Repository:
```bash
git clone https://github.com/your-repo/perfsonar-extensions.git
cd perfsonar-extensions
```

### Configure Target Hosts:

Edit `docker-compose.yml` and update:
```yaml
environment:
  - HOSTS=23.134.232.210 23.134.232.242
```
Add or remove hosts as needed.

### Configure Test frequency:

Edit `docker-compose.yml` and update:
```yaml
environment:
  - INTERVAL=0 */2 * * * # Example: Run every 2 hours
```
Change interval as needed.

---

## Usage

### Start Services:

```bash
docker-compose up -d <container_name>
```

### Stop Services:

```bash
docker-compose down
```

### View Logs:

```bash
docker logs perfsonar-testpoint
docker logs perfsonar-tool
```

Logs and results are stored in the `./data` directory for both services.

---

## Directory Structure

```
├── Dockerfile-perfsonar-testpoint  # Dockerfile for perfsonar-testpoint
├── Dockerfile-perfsonar-tool       # Dockerfile for perfsonar-tool
├── docker-compose.yml              # Compose file defining both services
├── compose/
│   └── psconfig/                   # Custom psconfig files for testpoint
├── data/                           # Stores logs and test results
└── README.md
```

---

## Areas for Improvement

- Additional documentation on test scheduling intervals and advanced configurations.
- Optional support for metrics visualization dashboards (Grafana, Prometheus).
- Integration scripts for alerting based on test failures or thresholds.