# Home Assistant App troubleshooting

Startup is intentionally fail-closed. The App never creates a SQLite production
database and never migrates PostgreSQL automatically.

- **Missing/invalid option:** correct `/data/options.json` through the App UI. The
  password is required and the port must be 1-65535.
- **PostgreSQL connection/authentication:** verify Synology listener/firewall,
  trusted LAN routing, port 55432, `home_energy`, `energy_app`, and its grants.
- **Schema mismatch:** back up PostgreSQL, run the reviewed Alembic upgrade from an
  operator workstation, verify `python -m alembic current`, then restart the App.
- **Core API/entity failure:** confirm `homeassistant_api: true`, restart Supervisor
  if its token is absent, and verify every required entity ID exists. The check is
  GET-only.
- **Watchdog restart:** inspect recent logs for three consecutive HA/database
  failures or collection age over 900 seconds. A single transient failure is not
  fatal.
- **No advancing rows:** ensure the App is running, wait for a five-minute boundary,
  check PostgreSQL from a trusted machine, and ensure no Windows collector is also
  running.

## Operational rollback

If the App cannot collect:

1. Stop the App and disable its automatic start temporarily.
2. Confirm no collector process remains and only one collector will run.
3. On Windows, set `DATABASE_URL` to the production Synology `home_energy` database
   using the appropriate application credential.
4. Run `python tools/run_collector.py`.
5. Confirm new PostgreSQL observations appear at five-minute boundaries.
6. Troubleshoot the App separately.

Do not point production collection back to SQLite. PostgreSQL remains authoritative.
