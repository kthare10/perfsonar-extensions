# perfSONAR Setup Helper 

This repository provides a convenience script, `perfsonar_setup.sh`, to automate the setup of perfSONAR nodes (shore/central archive or ship/remote).  
It configures `/etc/hosts`, installs perfSONAR, applies Logstash access controls, generates a psconfig, and publishes it.

---

## Usage

```bash
./perfsonar_setup.sh <SHORE_HOSTNAME> <SHORE_IP> <SHIP_HOSTNAME> <SHIP_IP> [options]
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
./perfsonar_setup.sh shore-STAR 23.134.232.50 ship-LOSA 23.134.233.34 --remote 23.134.232.50 --interval 2H
```

This:

* Updates `/etc/hosts`
* Installs perfSONAR
* Allows Logstash access
* Builds psconfig with `--remote 23.134.232.50` so results are archived to the central node
* Configures tests to run every 2 hours
* Validates, publishes, and registers the local psconfig

---

## Notes

* The script expects the following to exist in your repo:

  * `scripts/perfsonar-install.sh`
  * `scripts/allow_logstash_ips.sh`
  * `psconfig/psconfig_builder.py`
  * `psconfig/base_psconfig.json`
* Requires `sudo` for modifying `/etc/hosts`, installing perfSONAR, and running `psconfig` commands.
* The script is idempotent: `/etc/hosts` entries are replaced if already present, not duplicated.

---

## Typical Workflow

1. **Run on the Shore/Central Archive Node:**

   ```bash
   ./perfsonar_setup.sh shore-STAR 23.134.232.50 ship-LOSA 23.134.233.34 --no-add-tests
   ```
2. **Run on the Ship/Remote Node(s):**

   ```bash
   ./perfsonar_setup.sh shore-STAR 23.134.232.50 ship-LOSA 23.134.233.34 --remote 23.134.232.50 --interval 4H
   ```

This ensures the central archive is set up to manage configurations, while ship nodes push their results upstream at controlled intervals.
