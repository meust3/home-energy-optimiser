# Database backup, restore, and rollback

For SQLite, stop the collector and copy `data/energy_history.db`, or use SQLite's online backup API.

```powershell
pg_dump --format=custom --file home_energy.dump home_energy
pg_restore --clean --if-exists --dbname home_energy_restore home_energy.dump
```

Restore a plain SQL dump with `psql --dbname home_energy_restore --file dump.sql`. Test restores.

After production cutover, rollback means moving collection back to Windows while
keeping PostgreSQL authoritative: stop the App, ensure no other collector is
running, set Windows `DATABASE_URL` to `home_energy`, run
`python tools/run_collector.py`, and verify advancing slots. Do not resume
production collection against SQLite.

Home Assistant App backups cover App configuration, not the external PostgreSQL
history. Back up and test-restore `home_energy` independently on the Synology.
