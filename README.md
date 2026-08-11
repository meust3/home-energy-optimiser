# Home Energy Optimiser

> v0.5.0 is an unreleased release candidate. Forecast Operations and complete
> Reserve Audit are strictly advisory, opt-in, and disabled by default.

Version 0.5.0 keeps the existing one-container, one-process, one-collector design
and adds one lightweight coordinator thread. At aligned local boundaries it can
create genuine out-of-sample baseline forecasts, score only completed intervals
after a delay, and persist the existing reserve estimator's complete result. It
does not change forecast, reserve or opportunity algorithms and adds no device or
Home Assistant write path. See [forecast operations](docs/forecast_operations.md),
[scoring](docs/forecast_scoring.md), and [reserve persistence](docs/reserve_persistence.md).

The Home Assistant App options are:

```yaml
forecast_operations_enabled: false
forecast_interval_minutes: 30
forecast_horizon_hours: 24
forecast_alignment_minutes: 30
forecast_scoring_delay_minutes: 10
forecast_max_runtime_seconds: 120
reserve_snapshot_enabled: true
```

The v0.5.0 schema head is `20260812_01`. Migration is an explicit operator step;
the App never migrates PostgreSQL during startup. Validate the immutable image and
Home Assistant discovery before backing up, stopping the sole collector, upgrading
with `python -m alembic upgrade head`, verifying counts/revision, and immediately
updating the App. Forecast operations should be enabled only after collection is
healthy on v0.5.0.

A Home Assistant-connected, PostgreSQL-backed household energy optimisation
platform for forecasting demand, modelling battery reserve requirements, and
eventually supporting automated buy, sell, and charge decisions.

The project is personal infrastructure under active development. It currently
collects and analyses data but does not control Home Assistant or energy hardware.

## Current status

- **PostgreSQL production:** working and manually validated end to end
- **Continuous collector:** App v0.2.1 is installed and collecting successfully on
  the Home Assistant OS 18.1 NUC
- **Ingress dashboard:** v0.3.2 is published and awaits real-NUC installation
  verification
- **Reserve forecasting:** working and advisory
- **Solar and price forecasts:** Solcast and Amber Electric integrated
- **EV telemetry:** optional read-only vehicle-cloud integration is implemented for
  operational v0.4.0 vehicle telemetry release
- **Automated control or trading:** not enabled

PostgreSQL 17 on the Synology NAS is the canonical production source of truth. The
SQLite-to-PostgreSQL migration and exact validation are complete. Home Assistant
App v0.2.1 fixed Supervisor options-file permissions while retaining an
unprivileged application process; it is now the working production collector.
Version 0.3.0 added a strictly read-only Ingress presentation layer, and version
0.3.1 corrected App packaging metadata and documentation. Version 0.3.2 makes
sparse forecast, reserve, and normalized-flow data look intentional rather than
broken. The dashboard remains unverified on the production host until installation
testing is complete. Version 0.4.0 adds optional vehicle status, SOC, freshness,
home/away, and confirmed-charging detection without pretending raw vehicle battery
power is charger AC demand. It is not released or operational in production.

Forecast confidence can remain medium or low while household history is limited,
and EV charging may still be embedded in historical household demand.

## Architecture

```text
GoodWe / Amber / Solcast / weather
                 |
                 v
          Home Assistant Core
                 |
       GET-only state collection
                 |
       +---------+------------------+
       |                            |
       v                            v
Windows development          Home Assistant App
and offline analysis         v0.2.1 production collector
       |                            |
       +-------------+--------------+
                     v
          Home Energy Optimiser
                     |
                     v
      PostgreSQL 17 on Synology NAS
```

All application workflows use the backend selected by `DATABASE_URL`: collection,
history and flow inspection, reserve estimation, forecasting, reprocessing, EV
annotation, and exports.

## What it does today

- Collects Home Assistant telemetry on aligned five-minute slots.
- Stores observations and analytical records in PostgreSQL or compatible SQLite.
- Preserves raw inverter power and derives directional flows only from explicitly
  configured sign conventions.
- Builds explainable household-load history and demand forecasts.
- Estimates conservative battery reserve requirements and potentially tradable
  energy for manual review.
- Integrates Solcast solar forecasts and Amber import/export pricing.
- Stores forecast runs, projected-versus-actual comparisons, and derivation audits.
- Supports reversible manual EV-session annotation and optional fresh
  vehicle-reported charging detection without inventing EV power.
- Provides database, history, energy-flow, reserve, export, and health tooling.
- Presents existing stored observations and analytical records through an
  administrator-only Home Assistant Ingress dashboard and bounded GET-only API in
  the dashboard introduced in v0.3.0.

The dashboard does not run forecasts or reserve estimation. Persisted data may be
sparse, and the current schema stores only a subset of the complete reserve result.
Unavailable values remain unavailable rather than becoming zero. See
[dashboard architecture](docs/dashboard.md), [API routes](docs/dashboard_api.md),
and the [data contract](docs/dashboard_data_contract.md).

Fully missing chart series now show explicit accessible empty states instead of
blank axes. Partially available charts retain their valid series, reserve fields
distinguish unavailable run data from values not stored by the current schema, and
the Overview consolidates missing normalized directions into one concise note.

## Safety model

Safety is a hard architectural boundary:

- Home Assistant access is GET-only.
- No Home Assistant service endpoint is callable.
- No Modbus registers or coils are written.
- No inverter, battery, charger, or EV command path exists.
- No automatic grid charging, discharge, export, or trading is enabled.
- Reserve output is advisory and explicitly not execution-ready.
- The production App fails closed if PostgreSQL, its schema, or required Home
  Assistant reads are unavailable; it never falls back to SQLite.

An executor is deliberately absent. Any future control component requires a
separate safety review and controlled hardware validation.

## Database architecture

- **Production:** PostgreSQL `home_energy`, accessed by the least-privilege
  `energy_app` role.
- **Development:** PostgreSQL `home_energy_dev`, accessed by `energy_dev`.
- **Offline/tests:** SQLite remains supported for compatibility, local work, and
  the final pre-PostgreSQL backup.

PostgreSQL production migration is complete. `DATABASE_URL` selects exactly one
backend per process, and a selected PostgreSQL connection never silently falls
back to SQLite.

## Home Assistant App

The amd64 Home Assistant App deployment wrapper:

- uses the Supervisor Core API proxy;
- receives `SUPERVISOR_TOKEN` at runtime, so no user long-lived token is required;
- connects to external PostgreSQL configured through App options;
- validates connectivity, Alembic revision, application readiness, and required
  GET-only entity reads before collection;
- runs the existing five-minute collector as an unprivileged process;
- exposes a non-secret health endpoint for Supervisor watchdog checks;
- presents existing stored data through administrator-only Ingress and a bounded
  GET-only API introduced in v0.3.0.

Version 0.2.1 is the confirmed production collector. Version 0.3.2 is ready for
installation but has not been verified on the production NUC. Version 0.4.0 is an
unreleased schema-changing release candidate. See:

- [App design](docs/home_assistant_app.md)
- [Installation](docs/home_assistant_app_installation.md)
- [Troubleshooting and rollback](docs/home_assistant_app_troubleshooting.md)
- [Dashboard](docs/dashboard.md)
- [Read-only vehicle telemetry](docs/byd_vehicle_integration.md)
- [App Store introduction](home_energy_optimiser/README.md)
- [App page documentation](home_energy_optimiser/DOCS.md)
- [App changelog](home_energy_optimiser/CHANGELOG.md)

## Quick start — development

Python 3.12 or newer is required.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit the local `.env` with development-only values. Use `home_energy_dev` for
shared development or switch `DATABASE_URL` to SQLite for offline work. Never
commit `.env`.

## Useful commands

```powershell
python tools/collect_observation.py
python tools/run_collector.py
python tools/check_database.py --application-readiness
python tools/inspect_history.py
python tools/inspect_energy_flows.py
python tools/estimate_reserve.py --source live
```

These commands use the single configured persistence backend. Home Assistant-facing
commands remain read-only.

## Database migration

The production SQLite-to-PostgreSQL cutover has completed. The migration tooling is
retained for development, recovery, and audit use; dry-run is the default and
production writes require explicit confirmation. See
[database migration](docs/database_migration.md).

For v0.4.0, commit, push, build, container-test, tag, and validate the immutable
release before changing production PostgreSQL. Refresh Home Assistant and confirm
the update is discoverable before stopping v0.3.2 for the short migration/update
window. If the v0.4.0 App then fails, prefer the reviewed Windows v0.4.0 collector
against PostgreSQL revision `20260811_01`; rollback to v0.3.2 requires either a
physical `alembic downgrade 20260810_01` or restoration of the verified pre-release
dump. Never substitute `alembic stamp` for a physical schema downgrade.

## Documentation

- [Architecture](docs/architecture.md)
- [Database architecture](docs/database_architecture.md)
- [Data model](docs/data_model.md)
- [Database migration](docs/database_migration.md)
- [Backup and restore](docs/database_backup_restore.md)
- [Reserve estimation](docs/reserve_estimation.md)
- [Home Assistant App](docs/home_assistant_app.md)
- [Security](docs/security.md)
- [Multi-platform development](docs/multi_platform_development.md)

## Roadmap

1. Validate the App on the live Home Assistant OS NUC.
2. Move continuous 24/7 collection to the NUC.
3. Add read-only Home Assistant health/status entities and a dashboard.
4. Validate read-only vehicle telemetry, then integrate independent EV charger AC
   power.
5. Improve the demand model with longer household history.
6. Add a decision engine in advisory/shadow mode.
7. Introduce controlled automation only after explicit validation.
8. Optionally add an LLM explanation and analysis layer outside the control loop.

## Security and privacy

Secrets are supplied only at runtime. Local `.env`, databases, backups, logs, and
exports are ignored. The public-release audit found no committed real credentials
or sensitive tracked data, and the App redacts database and Supervisor credentials
from errors and health output.

Home Assistant and PostgreSQL should remain on a trusted LAN or private VPN. Public
source code does not include household history, local credentials, or production
database contents.

## License

Licensed under the [MIT License](LICENSE).
