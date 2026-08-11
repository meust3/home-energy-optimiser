# Home Assistant App troubleshooting

Startup is intentionally fail-closed. The App never creates a SQLite production
database and never migrates PostgreSQL automatically.

- **Options file not found:** confirm the App configuration was saved and restart
  the App so Supervisor remounts `/data/options.json`.
- **Options permission denied or unreadable:** use v0.2.1 or newer. Its root
  bootstrap copies the root-owned `0600` file without modifying the original, then
  runs Python as UID/GID 10001.
- **Malformed JSON or schema validation:** correct the configuration through the
  App UI. The password must be non-empty and the port must be 1-65535. Diagnostics
  deliberately omit all option values.
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
- **Blank Ingress page:** confirm v0.3.2 is installed, `ingress: true` and
  `ingress_port: 8099` are present in the manifest, then reload through the Home
  Assistant sidebar. Browser assets are relative to the trusted dynamic Ingress
  prefix; no host port should be added as a workaround.
- **Dashboard returns 403:** open it through authenticated Home Assistant Ingress.
  Direct LAN/container requests are intentionally rejected. A spoofed
  `X-Forwarded-For` or `X-Ingress-Path` cannot authorize access.
- **Missing charts:** select a shorter period and check collection coverage. Gaps
  are intentionally not interpolated. Forecast and reserve panels show empty states
  when no persisted run exists and never start a calculation.
- **Stale dashboard values:** compare the status observation age with `/health`,
  verify the PostgreSQL row advances, and inspect collector logs. Thirty-second
  browser polling does not change the five-minute collection frequency.
- **Dashboard API error:** a bounded browser query failure does not stop the
  collector or make watchdog unhealthy. Check PostgreSQL availability and App logs;
  errors intentionally omit SQL, paths, options, and credentials.

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
