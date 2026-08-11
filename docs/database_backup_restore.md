# Database backup, restore, and rollback

For v0.5.0, create and restore-test the production PostgreSQL dump only after the
immutable release artifact is validated and discoverable. Keep v0.4.0 collecting
until the maintenance window; then record counts and stop every collector before
`alembic upgrade head`. If the App fails after migration, prefer keeping revision
`20260812_01`, stopping the App, and running the reviewed v0.5.0 Windows collector
with forecast operations disabled and exactly one collector while troubleshooting.
Rollback to v0.4.0 requires a tested physical downgrade to `20260811_01` or restore
of the verified pre-v0.5.0 dump.

For SQLite, stop the collector and copy `data/energy_history.db`, or use SQLite's online backup API.

Before the v0.4.0 migration, keep v0.3.2 running and create and restore-test the
backup only after the immutable v0.4.0 image is validated and Home Assistant offers
the update:

```powershell
pg_dump --format=custom --file home_energy_pre_v0.4.0.dump --dbname home_energy
pg_restore --list home_energy_pre_v0.4.0.dump | Out-File home_energy_pre_v0.4.0.contents.txt
if (-not (Select-String -Path home_energy_pre_v0.4.0.contents.txt -Pattern "TABLE DATA public observations" -Quiet)) { throw "Verified dump does not contain observations table data" }
createdb home_energy_v040_restore_test
pg_restore --clean --if-exists --no-owner --no-privileges --dbname home_energy_v040_restore_test home_energy_pre_v0.4.0.dump
psql --dbname home_energy_v040_restore_test --command "SELECT COUNT(*) AS restored_observations FROM observations;"
```

Use protected client configuration. Keep the explicitly named temporary database,
record exact counts for every production application table, compare them with the
restored database, and run `dropdb home_energy_v040_restore_test` only after every
count matches. Stop v0.3.2 only after this restore test succeeds. Require the same
production counts after revision `20260811_01` and application-readiness checks.

Restore a plain SQL dump with `psql --dbname home_energy_restore --file dump.sql`. Test restores.

After production cutover, the preferred App-failure fallback is to keep PostgreSQL
at `20260811_01`: stop the App, ensure no other collector is running, set Windows
`DATABASE_URL` to `home_energy`, run the reviewed v0.4.0
`python tools/run_collector.py`, and verify advancing slots. Do not resume production
collection against SQLite.

App v0.3.2 can resume only after restoring the verified pre-v0.4.0 dump or running
`python -m alembic downgrade 20260810_01` from reviewed v0.4.0 source. The physical
downgrade removes only the nine nullable EV columns and therefore discards EV
telemetry collected after v0.4.0 began. Confirm the old revision, unchanged legacy
counts, and absent EV columns before starting v0.3.2. Never use `alembic stamp` to
pretend the physical schema was downgraded.

Home Assistant App backups cover App configuration, not the external PostgreSQL
history. Back up and test-restore `home_energy` independently on the Synology.
