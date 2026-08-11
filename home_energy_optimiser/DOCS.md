# Home Energy Optimiser

Home Energy Optimiser is a Home Assistant App that collects energy telemetry at
five-minute intervals, stores it in an external PostgreSQL database, and presents
the stored information in an administrator-only Ingress dashboard. It provides
explainable, advisory analysis; it does not operate energy equipment.

Version 0.3.2 is a release candidate and has not been verified on the production
Home Assistant OS host.

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

Independent EV telemetry is not yet integrated. EV charging can therefore remain
embedded in household consumption, and the dashboard must not be interpreted as
providing independently measured EV demand.

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

## Rollback to 0.2.1

Before rollback, take and verify a PostgreSQL backup and preserve the current App
configuration securely. Install version 0.2.1 through the supported Home Assistant
App version workflow, restart it, and verify database and collection health.
Version 0.2.1 retains the read-only collector but does not provide the v0.3.0
Ingress dashboard. The v0.3.2 release makes no database schema change, so no
database downgrade is required.
