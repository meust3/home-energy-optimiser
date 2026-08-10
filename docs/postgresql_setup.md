# PostgreSQL setup

The production `home_energy` cutover is complete and has been manually validated
with a fresh live observation. Home Assistant App v0.2.1 is the active 24/7
collector. The v0.3.0 Ingress dashboard remains an uninstalled release candidate.

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

Alembic reads `DATABASE_URL`; `alembic.ini` contains no credentials. Baseline downgrade is intentionally refused because dropping energy history is not a safe rollback.
