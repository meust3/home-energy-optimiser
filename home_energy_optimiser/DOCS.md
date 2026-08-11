# Home Energy Optimiser

Home Energy Optimiser is a Home Assistant App that collects energy telemetry at
five-minute intervals, stores it in an external PostgreSQL database, and presents
the stored information in an administrator-only Ingress dashboard. It provides
explainable, advisory analysis; it does not operate energy equipment.

Version 0.4.0 is an unreleased release candidate and has not been verified on the
production Home Assistant OS host. It requires Alembic revision `20260811_01`
before the App is updated; startup never runs migrations automatically.

## Read-only safety boundary

The App makes GET-only Home Assistant Core API requests. It makes no Home
Assistant service calls, inverter commands, charger commands, Modbus writes, or
automated trading decisions. Dashboard recommendations and reserve information
are advisory only.

## PostgreSQL requirements

The App requires a reachable external PostgreSQL database with the project's
current Alembic schema revision. Startup fails closed if the database cannot be
reached, authentication fails, or the schema revision differs. The App never
falls back to SQLite.

Create a dedicated least-privilege application account and configure PostgreSQL
to accept connections from the Home Assistant host. Use a hostname placeholder
such as `YOUR_NAS_HOST` when recording or sharing configuration. Keep database
credentials out of screenshots, logs, and support requests.

The PostgreSQL operator is responsible for database backups, restore testing,
retention, and database-server security. App backups are not a substitute for a
tested PostgreSQL backup.

## Configuration

- `db_host`: PostgreSQL hostname, for example `YOUR_NAS_HOST`.
- `db_port`: PostgreSQL listener port configured on the database server.
- `db_name`: Database containing the Home Energy Optimiser schema.
- `db_user`: Dedicated PostgreSQL application user.
- `db_password`: Password for the PostgreSQL application user. Store it only in
  the protected App configuration field.
- `timezone`: IANA timezone used for local display and scheduling boundaries.
- `health_max_observation_age_seconds`: Maximum accepted age of the latest
  observation before the health endpoint reports stale collection. The allowed
  range is 300 to 3600 seconds.
- `ev_vehicle_enabled`: Enables optional read-only vehicle state collection.
- `ev_charging_entity`, `ev_plugged_entity`, `ev_online_entity`,
  `ev_soc_entity`, `ev_battery_power_entity`, `ev_telemetry_updated_entity`, and
  `ev_location_entity`: Installation-specific optional IDs; empty means
  unconfigured.
- `ev_home_state`: Tracker state interpreted as at home.
- `ev_telemetry_stale_seconds`: Maximum dedicated vehicle telemetry age; defaults
  to 900 seconds.

The App receives `SUPERVISOR_TOKEN` from Home Assistant Supervisor at runtime and
uses it with the Supervisor Core API proxy. Users do not need to create or enter a
Home Assistant long-lived access token. The token is not displayed by the App.

## Starting and opening the App

1. Configure every required database field and save the App configuration.
2. Start the App and review its log for a successful database, schema, and Home
   Assistant readiness check.
3. Enable **Start on boot** so collection resumes after Home Assistant restarts.
4. Keep **Watchdog** enabled so Supervisor can monitor the non-secret health
   endpoint and restart an unhealthy App.
5. Select **Open Web UI**, or select **Energy Optimiser** in the Home Assistant
   sidebar. Dashboard and API routes are available only through authenticated,
   administrator-only Ingress.

## Dashboard pages

- **Overview** shows the latest stored energy state and recent summary data.
- **History** charts stored observations over a bounded time range.
- **Forecasts** compares persisted forecast points with available actual values.
- **Reserve** shows persisted advisory reserve estimates and their recorded
  context.
- **Data Quality** reports collection health, missing values, and freshness.

Unavailable values remain unavailable rather than being shown as zero. Forecasts
and Reserve show truthful empty states when no persisted runs or estimates exist;
opening those pages does not run a forecast or reserve calculation. The App has no
forecast scheduler.

Optional vehicle telemetry distinguishes plugged, charging, online, SOC, home/away,
and freshness. Raw vehicle battery power remains supporting vehicle-side data and
is not independently measured charger AC demand. Confirmed fresh charging rows are
excluded from baseline learning without inventing EV power, but complete EV energy
separation remains deferred until charger AC power is integrated and validated.

## Troubleshooting

### App will not start

Confirm all required configuration fields are present, PostgreSQL is reachable,
and Supervisor can provide Home Assistant Core API access. Review the App log;
startup errors are intentionally secret-safe.

### Database authentication failure

Verify `db_host`, `db_port`, `db_name`, and `db_user`, then re-enter
`db_password`. Confirm the PostgreSQL role has the required least-privilege access
and that server access rules permit the Home Assistant host.

### Schema revision mismatch

Do not bypass the startup check. Back up PostgreSQL, then apply the repository's
documented migration procedure from a trusted administration environment. Restart
the App only after the expected revision is present.

### Blank dashboard

Wait for the App startup checks to complete, reload the Ingress page, and inspect
the App log and Watchdog health. A new database can legitimately contain too
little data to chart.

### Dashboard returns 403

Open the dashboard through Home Assistant's **Open Web UI** action or sidebar as
an administrator. Direct access to the internal App port is intentionally denied.

### Stale observations

Check Home Assistant entity availability, database connectivity, App logs, and
the configured `health_max_observation_age_seconds`. Do not replace missing
telemetry with invented values.

### No forecast data

The dashboard reads stored forecast results only. Confirm an existing supported
forecast workflow has persisted data; the App does not schedule or calculate
forecasts when a page is opened.

## Migration and rollback

Before production migration, validate the exact commit image and immutable v0.4.0
tag, merge the release, and confirm Home Assistant offers the update without
installing it. Then create and restore-test a custom-format PostgreSQL dump, record
all application-table counts, stop v0.3.2 and every other collector, apply
`python -m alembic upgrade head` from reviewed v0.4.0 source, run
`python tools/check_database.py --application-readiness`, and require revision
`20260811_01` with unchanged counts. Immediately update and start v0.4.0. See the
repository vehicle-integration runbook for the exact sequence.

## Rollback to 0.3.2

Prefer stopping the failed App and running the reviewed Windows v0.4.0 collector
against unchanged PostgreSQL revision `20260811_01` with exactly one collector.

Before App rollback, take and verify another PostgreSQL backup and stop every
collector. Restore the verified pre-v0.4.0 dump or run
`python -m alembic downgrade 20260810_01` from reviewed v0.4.0 source. The downgrade
removes only the nine nullable vehicle fields and therefore discards EV telemetry
collected after v0.4.0 began while preserving legacy rows and fields. Confirm the
old revision, unchanged legacy counts, and absent EV columns before installing and
starting v0.3.2. Never use `alembic stamp` as a physical rollback.
