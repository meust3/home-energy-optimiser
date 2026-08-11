# PostgreSQL setup

The production `home_energy` cutover is complete and has been manually validated
with a fresh live observation. Home Assistant App v0.4.0 is the active 24/7
collector at schema revision `20260811_01`.

Recommended Synology layout:

```text
Synology NAS
  PostgreSQL: home_energy, home_energy_dev
Home Assistant NUC
  Home Assistant App production collector -> home_energy as energy_app
Developer computers
  -> home_energy_dev as energy_dev
  -> home_energy as energy_readonly for production analysis
GitHub
  source only
SQLite
  offline fallback and tests
```

Create databases and roles through PostgreSQL administration outside this application. Do not use an administrator account in `DATABASE_URL`. Grant `energy_app` only required production privileges, `energy_dev` only development privileges, and `energy_readonly` SELECT access. The application never creates users.

Expose PostgreSQL only on trusted LAN or Tailscale, with TLS where available—never directly to the public internet.

```powershell
python -m alembic upgrade head
python -m alembic current
python -m alembic history
python tools/check_database.py
```

Before any v0.4.0 production migration, build and validate the immutable release
artifact and confirm Home Assistant can discover the update without installing it.
Then verify a custom-format `pg_dump` by restoring it, record observation counts,
stop the v0.3.2 App, confirm no other collector is running, apply Alembic head
`20260811_01`, run `python tools/check_database.py --application-readiness`, and
confirm observation counts are unchanged before immediately updating the App. See
[vehicle integration](byd_vehicle_integration.md).

Alembic reads `DATABASE_URL`; `alembic.ini` contains no credentials. Historical
baseline downgrades remain intentionally refused because dropping energy history is
not a safe rollback. The tested v0.4.0 downgrade is different: it physically removes
only the nine nullable EV telemetry columns and discards EV telemetry collected after
v0.4.0 began. Never substitute `alembic stamp` for that physical downgrade.
