# Security and safety boundary

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

App database options are read once from Supervisor-managed `/data/options.json`.
The password is represented as a secret, URL-encoded during connection-string
construction, and redacted from errors. Startup fails closed on PostgreSQL or
schema failure and cannot select SQLite. External PostgreSQL backups remain the
operator's responsibility and are not included in Home Assistant App backups.

The local database can reveal occupancy patterns, energy use, and household
behavior. Keep it private, protect backups, and share only deliberately sanitized
exports. The database contains observations, not Home Assistant credentials.
Schema migration is additive: it preserves existing observation rows and adds local
health metadata only.

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
