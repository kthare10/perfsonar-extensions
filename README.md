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
- [Setup Measurement Container](#setup-measurement-container)

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
docker compose up -d perfsonar-testpoint
docker exec -it perfsonar-testpoint /bin/bash /etc/cron.hourly/bootstrap_cron.sh
```

---

### 2. **perfsonar-tool**

A lightweight container based on `rocky:9` that installs PerfSONAR command-line tools and runs periodic network tests on specified hosts.

**Launch:**
```bash
docker compose up -d perfsonar-tool
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
  - CRON_EXPRESSION=0 */2 * * * # Example: Run every 2 hours
```
Change interval as needed.

---

## Usage

### Start Services:

```bash
docker compose up -d <container_name>
```

### Stop Services:

```bash
docker compose down
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
├── data_testpoint/                 # Stores logs and test results for testpoint container
├── data_tools/                     # Stores logs and test results for tool container
└── README.md
```

## Setup Measurement Container

### **Instructions for the Ubuntu VM (Student Environment)**

1. **Provision or connect** to the Ubuntu VM onboard the ship.

2. **Clone the repository and install Docker**:

```bash
git clone https://github.com/kthare10/perfsonar-extensions.git
cd perfsonar-extensions
./enable_docker.sh
```

3. **Update the `AUTH_TOKEN`** in the `docker-compose.yml` file under the `environment` section of the `perfsonar-testpoint` service.  
   We will provide the `AUTH_TOKEN` value.

```yaml
services:
  perfsonar-testpoint:
    ...
    environment:
      - AUTH_TOKEN=<insert_token_here>
```

4. **Bring up the containers and initialize the scheduler**:

```bash
docker compose up -d perfsonar-testpoint
docker exec -it perfsonar-testpoint /bin/bash /etc/cron.hourly/bootstrap_cron.sh
```

> **Note:** This container is configured to automatically run tests every 2 hours and store the results in:  
> `perfsonar-extensions/data_testpoint`

5. **At the end of the cruise**, archive and export the test results:

```bash
tar -zcvf data_testpoint.tgz perfsonar-extensions/data_testpoint
```

The resulting archive can then be transferred to a student’s laptop or uploaded to a cloud storage location for us to retrieve.
