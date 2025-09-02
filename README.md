# perfsonar-extensions

Automation and reference artifacts for deploying perfSONAR either with containers or natively on VMs.

---

## Choose your setup

- **Docker-based setup** – Run perfSONAR components in containers with Compose.  
  See: [docker/README.md](docker/README.md)

- **Native setup** – Install perfSONAR directly on a VM/host.  
  See: [native/README.md](native/README.md)

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
````

---

## What’s in this repo

* `docker/` – Containerized deployment (Compose files, images, env examples).
* `native/` – VM/host installation scripts, psconfig builder, helpers.


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
