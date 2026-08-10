# SQLite to PostgreSQL migration

The source database is opened read-only. The tool traverses tables in foreign-key-safe order, uses batches and transactions, preserves keys/NULL/JSON/boolean/timestamp values, and reports unequal existing rows as conflicts. Dry run is default; writing requires `--apply`. A database named `home_energy` additionally requires `--confirm-production`.

```powershell
python tools/migrate_sqlite_to_postgres.py --source-sqlite data/energy_history.db --target-database-url "postgresql+psycopg://energy_dev:PASSWORD@NAS:5432/home_energy_dev"
python tools/migrate_sqlite_to_postgres.py --source-sqlite data/energy_history.db --target-database-url "postgresql+psycopg://energy_dev:PASSWORD@NAS:5432/home_energy_dev" --apply
python tools/migrate_sqlite_to_postgres.py --source-sqlite data/energy_history.db --target-database-url "postgresql+psycopg://energy_dev:PASSWORD@NAS:5432/home_energy_dev" --validate-only --validation-mode exact
python tools/migrate_sqlite_to_postgres.py --source-sqlite data/energy_history.db --target-database-url "postgresql+psycopg://energy_dev:PASSWORD@NAS:5432/home_energy_dev" --validate-only --validation-mode source-preserved
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
