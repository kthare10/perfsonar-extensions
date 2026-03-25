# perfsonar-extensions

Automation and reference artifacts for deploying perfSONAR either with containers or natively on VMs.

---

## Choose your setup

- **Docker-based setup** – Run perfSONAR components in containers with Compose.
  See: [docker/README.md](docker/README.md)

- **Native setup** – Install perfSONAR directly on a VM/host.
  See: [native/README.md](native/README.md)

- **NMEA listener** *(optional)* – Capture NMEA 0183 navigation data (GPS, heading, motion) from research vessel broadcasts and archive it alongside perfSONAR results for correlation.
  See: [nmea-listener/README.md](nmea-listener/README.md)

---

## Quick start

If you already know your path:

```bash
# Docker-based deployment
cd docker
# follow docker/README.md

# Native deployment
cd native
# follow native/README.md

# NMEA listener (vessel deployments only)
cd nmea-listener
# follow nmea-listener/README.md
```

---

## What's in this repo

* `docker/` – Containerized perfSONAR testpoint deployment (Compose files, images, env examples).
  See: [docker/README.md](docker/README.md)
* `native/` – VM/host installation scripts, psconfig builder, helpers.
  See: [native/README.md](native/README.md)
* `nmea-listener/` – NMEA 0183 navigation data listener for research vessels (GPS, heading, roll/pitch/heave).
  See: [nmea-listener/README.md](nmea-listener/README.md)

> Exact structure may vary slightly; refer to each sub-README for authoritative steps.

---
## Requirements

* Linux host or VM (tested on recent Ubuntu 24 variants).
* `sudo` access.
* For Docker path: Docker Engine + Docker Compose.
* For native path: system package manager, Python 3.

---

## Contributing

* Open an issue for bugs or requests.
* Use PRs for changes; keep Docker and native instructions in their respective directories.

---

## License

MIT (or your chosen license). See `LICENSE`.
