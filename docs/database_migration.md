# SQLite to PostgreSQL migration

The v0.5.1 application head is `20260813_01`, and production is expected to
already be at that revision before this App-only update. Confirm with
`python -m alembic current` and `python tools/check_database.py
--application-readiness`; do not run an unnecessary upgrade or downgrade. Startup
never migrates. For development and recovery exercises from `20260812_01`, the
physical upgrade is `python -m alembic upgrade 20260813_01` and rollback is
`python -m alembic downgrade 20260812_01`. The downgrade removes only v0.5.1
rollup/maintenance data. Never substitute `alembic stamp`.

## v0.5.0 revision 20260812_01

Do not migrate production until the exact v0.5.0 commit image and immutable tag have
passed validation and Home Assistant can discover the update. Then restore-test a
fresh PostgreSQL dump, record observation/table counts, stop the v0.4.0 App and
confirm no other collector, and run from reviewed v0.5.0 source:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://energy_app:REDACTED@HOST:55432/home_energy"
python -m alembic current
python -m alembic upgrade head
python -m alembic current
python tools/check_database.py --application-readiness
```

Require revision `20260812_01` and unchanged observation/legacy counts, then update
and start v0.5.0 immediately. The App does not migrate on startup.

The physical rollback is `python -m alembic downgrade 20260811_01` from reviewed
v0.5.0 source. It removes only v0.5.0 score/attempt/reserve tables and therefore
discards their audit history; observations and legacy forecasts remain. Never use
`alembic stamp` as schema rollback. A database restore is the alternative.

Production migration to `home_energy` has completed and exact validation passed.
This document remains the operational reference for development migrations,
recovery exercises, and audit validation; it is not a pending production task.

The source database is opened read-only. The tool traverses tables in foreign-key-safe order, uses batches and transactions, preserves keys/NULL/JSON/boolean/timestamp values, and reports unequal existing rows as conflicts. Dry run is default; writing requires `--apply`. A database named `home_energy` additionally requires `--confirm-production`.

```powershell
python tools/migrate_sqlite_to_postgres.py --source-sqlite data/energy_history.db --target-database-url "postgresql+psycopg://energy_dev:YOUR_DB_PASSWORD@YOUR_NAS_HOST:55432/home_energy_dev"
python tools/migrate_sqlite_to_postgres.py --source-sqlite data/energy_history.db --target-database-url "postgresql+psycopg://energy_dev:YOUR_DB_PASSWORD@YOUR_NAS_HOST:55432/home_energy_dev" --apply
python tools/migrate_sqlite_to_postgres.py --source-sqlite data/energy_history.db --target-database-url "postgresql+psycopg://energy_dev:YOUR_DB_PASSWORD@YOUR_NAS_HOST:55432/home_energy_dev" --validate-only --validation-mode exact
python tools/migrate_sqlite_to_postgres.py --source-sqlite data/energy_history.db --target-database-url "postgresql+psycopg://energy_dev:YOUR_DB_PASSWORD@YOUR_NAS_HOST:55432/home_energy_dev" --validate-only --validation-mode source-preserved
```

`exact` is the conservative default: the whole target must mirror the source, so
any extra target row fails. `source-preserved` verifies every source primary key and
value while allowing and separately reporting later target rows, their slot range,
and a raw-telemetry hash over the source-key subset. Missing or conflicting source
rows fail in either mode; target extras can never mask a mismatch. Validation also
checks relational integrity. Interrupted runs can be repeated: equal business keys
are skipped and unequal rows are never overwritten. `--resume` records operator
intent.

After validation, set `DATABASE_URL` once for the process. All collection and
analysis commands then use the PostgreSQL target; no component should retain a
separate SQLite path.

Adopt an existing schema-version-6 SQLite database without recreation:

```powershell
python tools/adopt_database.py
python tools/adopt_database.py --apply
```

## v0.4.0 PostgreSQL schema migration

Revision `20260811_01` adds nine nullable EV telemetry columns. Do not migrate
production until the exact commit image and immutable `v0.4.0` tag have both passed
container validation and Home Assistant offers the update. Keep v0.3.2 running
while creating and restore-testing the pre-migration dump. Then record all table
counts, stop every collector, and run from reviewed v0.4.0 source with a protected
`DATABASE_URL`:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe tools\check_database.py --application-readiness
```

Require `20260811_01` and unchanged table counts, then immediately update and start
the already-discoverable v0.4.0 App.

The preferred App-failure fallback keeps revision `20260811_01` and runs the
reviewed Windows v0.4.0 collector against production PostgreSQL with exactly one
collector active. A v0.3.2 rollback requires a maintenance window and either:

```powershell
.\.venv\Scripts\python.exe -m alembic downgrade 20260810_01
.\.venv\Scripts\python.exe -m alembic current
```

or restoration of the verified pre-v0.4.0 dump. The downgrade removes only the
nine nullable EV fields, so legacy fields and rows remain, but EV telemetry collected
after v0.4.0 started is discarded. Verify revision `20260810_01`, unchanged legacy
counts, and absent EV columns before starting v0.3.2. Never use `alembic stamp` as a
schema rollback. The complete sequence is in
[the vehicle integration runbook](byd_vehicle_integration.md).
