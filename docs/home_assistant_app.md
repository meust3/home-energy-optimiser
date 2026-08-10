# Home Assistant App design

Home Energy Optimiser is packaged as a Home Assistant App (formerly called an
add-on) without changing collector business logic. This is release-candidate
packaging: it has not yet been installed or proven operational on the real Home
Assistant OS NUC.

```text
Home Assistant Core
  GET via http://supervisor/core/api + SUPERVISOR_TOKEN
       |
Home Energy Optimiser App on HAOS amd64 (release candidate)
  existing tools/run_collector.py, one process, five-minute boundaries
       |
Synology PostgreSQL 17
  home_energy / energy_app / external port 55432
```

## Least privilege and authentication

`homeassistant_api: true` causes Supervisor to inject `SUPERVISOR_TOKEN`. The App
uses that token as the bearer credential for the internal Core REST proxy, so a
user-managed long-lived Home Assistant token is unnecessary. The existing client
allows only `GET /api/`, `GET /api/states`, and entity-state GETs.

The App does not enable `hassio_api`, ingress, host networking, privileged mode,
device mappings, USB/GPIO, the Docker socket, Home Assistant configuration access,
or elevated Linux capabilities. Port 8099 is internal and used by Supervisor only.

## Startup and runtime

The Python launcher reads Supervisor-managed `/data/options.json`; validates host,
port, database, username, password, timezone, and health settings; URL-encodes the
credential components; and exports one explicit `DATABASE_URL`. It then verifies:

1. the URL is PostgreSQL, never SQLite;
2. PostgreSQL connectivity and authentication;
3. Alembic revision `20260810_01`;
4. tables needed for collection and analytical consumers;
5. the Core API through the Supervisor proxy;
6. all required collector entities through GET requests.

No migration runs automatically. Any failure exits non-zero before collection and
Supervisor reports/restarts the failed App. Once ready, the launcher executes the
existing collector. Writes retain bounded retry, transaction rollback, and
duplicate-slot protection. Supervisor owns crash restart; there is no shell restart
loop or cron.

`SIGTERM` and `SIGINT` set an interruptible stop event. No new collection starts,
an active call/transaction is allowed to return or roll back, database resources
close in `finally`, and the process exits.

## Health and future entities

`GET /health` contains only component status, last successful collection and slot,
age, and App version. Startup receives one threshold period of grace. One transient
failure is tolerated; three consecutive component failures or an overdue successful
collection makes the endpoint return HTTP 503 for Supervisor watchdog recovery.

A later read-only Home Assistant integration may expose collector status, latest
observation, database status, forecast confidence, recommended reserve, and
potentially tradable energy. This release creates no Home Assistant entities.

## Image and data ownership

The amd64 image uses an explicit Python 3.12 slim base, installs only project
runtime dependencies from `pyproject.toml`, and executes `run.sh`, which uses
`exec python tools/run_home_assistant_app.py`. `.git`, `.env`, SQLite files, caches,
tests, logs, and local exports are excluded. `/data` contains Supervisor options,
not the production datastore.
The runtime process uses an unprivileged UID. The health server binds to the
container interface because Supervisor's watchdog must reach `[HOST]`; its port has
no host publication and exposes only non-secret status JSON on the internal App
network.

Removing, upgrading, or rebuilding the App does not remove PostgreSQL history.
Home Assistant backups are not PostgreSQL backups; `home_energy` needs a separate,
tested Synology backup workflow.
