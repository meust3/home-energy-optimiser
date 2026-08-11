# Security and safety boundary

v0.5.0 adds analytical database writes only. The coordinator imports no Home
Assistant client, service API, Modbus or device-control implementation. It starts no
worker/process/collector, exposes no run-now route, and stores only a bounded
exception class in operation failures. APIs omit database URLs, tokens, passwords
and raw App options; all query ranges and row counts are bounded.

## Read-only operation

Phase 1 can call only `GET /api/`, `GET /api/states`, and
`GET /api/states/<entity_id>`. The client contains no POST, PUT, PATCH, DELETE,
service-call, Modbus, or hardware-control API. It rejects paths outside that
allowlist. The package includes no control entity IDs and no executor.

## Token handling

`HA_TOKEN` is loaded from the environment or local `.env`. Its model field is
excluded from serialization and representation. It is never printed, logged,
placed in test fixtures, or stored in any database. Network exception messages are
redacted before being raised.

Inside the Home Assistant App, no long-lived token is configured. Supervisor
provides `SUPERVISOR_TOKEN` because `homeassistant_api: true` is declared. The App
maps it in memory to the existing secret-excluded collector configuration and uses
the internal Core proxy. It never writes it to `/data`, logs, health output, or the
database. `hassio_api`, host networking, privileged mode, the Docker socket, Home
Assistant configuration access, devices, USB, GPIO, `SYS_ADMIN`, and `NET_ADMIN`
are not requested.

## Ignored local files

`.env`, `.venv`, SQLite files under `data/`, and `logs/` are ignored by Git. Check
`git status` before every commit and never add credentials with a force option.
The pre-publication audit found no real credential or sensitive data file in the
tracked tree or reachable Git history. The local `.env` remains private and was
never committed.

## Database privacy

`DATABASE_URL` may contain credentials. Diagnostic output uses safe target display
and exception redaction and never prints an unredacted URL. Use `energy_app`,
`energy_dev`, and `energy_readonly` under least privilege. PostgreSQL must remain on
trusted LAN/Tailscale rather than the public internet.

Supervisor mounts App options as root-owned `/data/options.json` with mode `0600`.
A narrowly scoped root entrypoint copies it to an `app:app`, mode-`0600` file under
`/run`, then uses `exec gosu` to run Python, the collector, and watchdog/Ingress server as
UID/GID 10001. Python removes the ephemeral copy after successful parsing; the
original Supervisor file is never modified or deleted. The password is represented
as a secret, URL-encoded during connection-string construction, and redacted from
errors. Startup fails closed on PostgreSQL or schema failure and cannot select
SQLite. External PostgreSQL backups remain the operator's responsibility and are
not included in Home Assistant App backups.

The local database can reveal occupancy patterns, energy use, and household
behavior. Keep it private, protect backups, and share only deliberately sanitized
exports. The database contains observations, not Home Assistant credentials.
Schema migration is additive: it preserves existing observation rows and adds local
health metadata only.

## Ingress dashboard

Version 0.3.0 relies on Home Assistant Ingress authentication and adds no password
system. Dashboard, API, and static requests are authorized from the actual socket
peer only: `172.30.32.2` in Home Assistant or loopback in tests. `/health` remains
available to Supervisor watchdog. `X-Forwarded-For` is ignored, and
`X-Ingress-Path` is accepted only after peer authorization and only as a normalized
relative prefix. Home Assistant user identity headers are not logged or persisted.

The server supports only GET. POST, PUT, PATCH, and DELETE return 405; no control,
configuration, estimator, forecast-runner, or database-write endpoint exists.
Ranges are capped at 31 days, observation reads at 9,000 rows, and browser series at
2,500 points. Query columns and ordering are fixed in repository code.

HTML, CSS, and JavaScript are local package assets. Responses use `nosniff`,
`no-referrer`, a same-origin/local-asset Content Security Policy compatible with
same-origin Ingress framing, and `no-store` for HTML and APIs. No CORS, analytics,
remote font, CDN, or external request is configured. Errors use stable messages and
never return exceptions, SQL, database URLs, options, authorization headers, or
filesystem paths.

## Future executor separation

Any future executor must be a separately reviewed component, disabled by default,
and introduced only after controlled hardware testing and explicit approval. It
must never be smuggled into the collector, forecaster, or advisory optimiser.
Domain readiness checks are advisory guards; they do not introduce an executor or
any Home Assistant write capability.

History inspection, CSV export, and power-sign validation read local observations
only. Exports inherit the database's privacy sensitivity and should remain under
`data/` or another protected location. Sign-analysis output is statistical evidence,
not authority to control the inverter.

Optional weather entities use the same allowlisted `GET /api/states` call. They do
not add endpoints or write capabilities and are not mandatory for overall health.

Optional EV sensors and helpers are also GET-only. The project does not create or
change helpers, charger state, inverter settings, or Modbus registers. Energy-flow
normalization never overwrites raw power. Forecast comparison writes only derived
actual/error values to the configured database.

The v0.4.0 vehicle path reads configured state entities in that same bulk GET. It
does not retain Home Assistant attributes. Location is reduced to an at-home
boolean, and no schema or API field exists for VIN, latitude, longitude, precise
home coordinates, GPS history, or journeys. Raw vehicle battery power is explicitly
separate from charger AC demand. No vehicle control entity, force-poll action,
poll-interval change, service endpoint, or dashboard mutation route is present.
