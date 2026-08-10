# Database backup, restore, and rollback

For SQLite, stop the collector and copy `data/energy_history.db`, or use SQLite's online backup API.

```powershell
pg_dump --format=custom --file home_energy.dump home_energy
pg_restore --clean --if-exists --dbname home_energy_restore home_energy.dump
```

Restore a plain SQL dump with `psql --dbname home_energy_restore --file dump.sql`. Test restores.

Rollback cutover by stopping the PostgreSQL-backed collector, restoring the prior SQLite `DATABASE_URL` (or removing it for fallback), restarting, verifying the latest slot with `inspect_history.py`, and preserving PostgreSQL unchanged for investigation.
