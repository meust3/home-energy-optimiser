# Home Assistant App design

Version 0.5.0 retains one container, one Python process, one collector and
one dashboard server. The optional forecast coordinator is a single in-process
thread, disabled by default. Supervisor health reports scheduler and reserve status
separately; one forecast failure is a warning and does not make core collection
unhealthy. Three consecutive failures report degraded scheduler status without
creating a watchdog restart loop.

Home Energy Optimiser is packaged as a Home Assistant App (formerly called an
add-on) without changing collector business logic. Version 0.4.1 is installed and
collecting successfully on the amd64 Home Assistant OS 18.1 NUC with optional
privacy-minimized vehicle telemetry and PostgreSQL revision `20260811_01`.
Version 0.3.0 introduced the administrator-only read-only Ingress dashboard,
v0.3.2 added resilient sparse-data presentation, v0.4.0 added vehicle telemetry,
and v0.4.1 added schema-neutral power-sign options and normalized-flow repair.

```text
Home Assistant Core
  GET via http://supervisor/core/api + SUPERVISOR_TOKEN
       |
Home Energy Optimiser App on HAOS amd64
  one collector + one internal watchdog/Ingress server
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

The App enables Home Assistant Ingress without `hassio_api`, host networking,
privileged mode, device mappings, USB/GPIO, the Docker socket, Home Assistant
configuration access, or elevated Linux capabilities. Port 8099 is internal and has
no host publication. `panel_admin: true` limits the experimental panel to Home
Assistant administrators.

## Startup and runtime

The container entrypoint starts as root solely to read Supervisor-managed
`/data/options.json`. It creates `/run/home-energy-optimiser`, copies the options to
`options.json`, assigns that copy to `app:app` with mode `0600`, and exports its path
as `HOME_ENERGY_APP_OPTIONS_PATH`. It never modifies, changes ownership or mode of,
or deletes the original `/data/options.json`.

The entrypoint then uses `exec gosu app:app` to run Python as UID/GID 10001 while
preserving Supervisor's runtime environment. Python validates host, port, database,
username, password, timezone, and health settings, then immediately unlinks the
ephemeral copy after successful parsing. It URL-encodes the credential components
and exports one explicit `DATABASE_URL`.

Version 0.4.1 also validates and exports `GRID_POWER_SIGN`,
`BATTERY_POWER_SIGN`, `SIGN_CONVENTION_CONFIDENCE`,
`SIGN_CONVENTION_SUPPORTING_SAMPLES`, and `BALANCE_TOLERANCE_W`. Both signs must
remain unknown with unconfirmed/zero evidence, or both must be configured with
confirmed confidence and supporting samples. Startup logs only these non-secret
values, never the full options payload. It does not automatically repair history.

It then verifies:

1. the URL is PostgreSQL, never SQLite;
2. PostgreSQL connectivity and authentication;
3. the exact expected Alembic revision (`20260811_01` since v0.4.0);
4. tables needed for collection and analytical consumers;
5. the Core API through the Supervisor proxy;
6. all required collector entities through GET requests.

No migration runs automatically. Any failure exits non-zero before collection and
Supervisor reports/restarts the failed App. Once ready, the launcher executes the
existing collector. Writes retain bounded retry, transaction rollback, and
duplicate-slot protection. Supervisor owns crash restart; there is no shell restart
loop or cron.

Because both the shell and `gosu` use `exec`, `SIGTERM` and `SIGINT` reach Python.
They set an interruptible stop event. No new collection starts,
an active call/transaction is allowed to return or roll back, database resources
close in `finally`, and the process exits.

## Health and future entities

`GET /health` contains only component status, last successful collection and slot,
age, and App version. Startup receives one threshold period of grace. One transient
failure is tolerated; three consecutive component failures or an overdue successful
collection makes the endpoint return HTTP 503 for Supervisor watchdog recovery.

The same server presents the v0.3.0 dashboard and versioned GET-only API. Dashboard,
API, and static routes accept only the actual network peer `172.30.32.2`, while
loopback is available for tests. `/health` remains reachable by Supervisor watchdog.
`X-Forwarded-For` and Home Assistant identity headers are neither trusted nor
stored. `X-Ingress-Path` is used only after peer authorization to construct a safe
relative browser base path. This release creates no Home Assistant entities.

Optional v0.4.0 vehicle entity IDs are supplied through App options and mapped to
normal environment configuration. Empty values are unconfigured. The collector
reads configured states through the same bulk GET; optional failures remain in the
EV readiness result and cannot fail startup or core collection. See
[vehicle integration](byd_vehicle_integration.md).

## Image and data ownership

The amd64 image uses an explicit Python 3.12 slim base, installs only project
runtime dependencies from `pyproject.toml`, and executes `run.sh`, which performs
the options bootstrap and then uses `exec gosu app:app python`. `.git`, `.env`, SQLite files, caches,
tests, logs, and local exports are excluded. `/data` contains Supervisor options,
not the production datastore.
Only the short file-preparation bootstrap runs as root. The Python application,
collector, and web server run as unprivileged UID/GID 10001. The web server binds to the
container interface because Supervisor's watchdog must reach `[HOST]`; its port has
no host publication. Ingress pages and APIs expose only bounded, non-secret,
read-only presentation data on the internal App network.

The frontend is server-rendered HTML plus package-local CSS and vanilla JavaScript.
It has no CDN, web font, analytics, chart dependency, CORS, or second authentication
system. Browser requests use short-lived repositories and cannot change collector
health. No endpoint runs forecasts, reserve estimation, or device control.

Removing, upgrading, or rebuilding the App does not remove PostgreSQL history.
Home Assistant backups are not PostgreSQL backups; `home_energy` needs a separate,
tested Synology backup workflow.
