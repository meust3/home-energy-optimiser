# Home Energy Optimiser

A Home Assistant-connected, PostgreSQL-backed household energy optimisation
platform for forecasting demand, modelling battery reserve requirements, and
eventually supporting automated buy, sell, and charge decisions.

The project is personal infrastructure under active development. It currently
collects and analyses data but does not control Home Assistant or energy hardware.

## Current status

- **PostgreSQL production:** working and manually validated end to end
- **Continuous collector:** working on Windows; Home Assistant App packaging ready
  for its first HAOS test
- **Reserve forecasting:** working and advisory
- **Solar and price forecasts:** Solcast and Amber Electric integrated
- **EV telemetry:** not yet independently integrated
- **Automated control or trading:** not enabled

PostgreSQL 17 on the Synology NAS is the canonical production source of truth. The
SQLite-to-PostgreSQL migration and exact validation are complete. The Home
Assistant App (formerly called an add-on) is a release candidate; it has not yet
been installed or proven operational on the Home Assistant OS NUC.

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
and current collector        amd64 release candidate
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
- Supports reversible manual EV-session annotation without inventing EV power.
- Provides database, history, energy-flow, reserve, export, and health tooling.

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
- exposes a non-secret health endpoint for Supervisor watchdog checks.

The package is ready for release-candidate testing but has not completed live HAOS
validation. See:

- [App design](docs/home_assistant_app.md)
- [Installation](docs/home_assistant_app_installation.md)
- [Troubleshooting and rollback](docs/home_assistant_app_troubleshooting.md)

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
4. Integrate independent EV charger telemetry.
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
