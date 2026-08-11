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
- **Power-sign schema validation:** signs must be either both unknown with
  unconfirmed confidence and zero samples, or both explicitly configured with
  low/medium/high confidence and at least one supporting sample. Balance tolerance
  must be positive.
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
- **Blank Ingress page:** confirm v0.3.2 or newer is installed, `ingress: true` and
  `ingress_port: 8099` are present in the manifest, then reload through the Home
  Assistant sidebar. Browser assets are relative to the trusted dynamic Ingress
  prefix; no host port should be added as a workaround.
- **Dashboard returns 403:** open it through authenticated Home Assistant Ingress.
  Direct LAN/container requests are intentionally rejected. A spoofed
  `X-Forwarded-For` or `X-Ingress-Path` cannot authorize access.
- **Missing charts:** select a shorter period and check collection coverage. Gaps
  are intentionally not interpolated. Forecast and reserve panels show empty states
  when no persisted run exists and never start a calculation.
- **Grid/battery charts say signs are not configured:** raw telemetry is still
  preserved. Configure the locally validated sign pair, restart, and verify a new
  normalized observation. Historical rows remain null until the separately
  backup-gated v0.4.1 reprocessing command is run; startup never repairs history.
- **Stale dashboard values:** compare the status observation age with `/health`,
  verify the PostgreSQL row advances, and inspect collector logs. Thirty-second
  browser polling does not change the five-minute collection frequency.
- **Dashboard API error:** a bounded browser query failure does not stop the
  collector or make watchdog unhealthy. Check PostgreSQL availability and App logs;
  errors intentionally omit SQL, paths, options, and credentials.
- **Vehicle integration disabled:** enable it only after entering the available
  installation-specific entity IDs. Empty optional IDs are accepted.
- **Vehicle status stale or unknown:** verify the dedicated telemetry timestamp,
  online state, and configured freshness threshold. The App will not force a cloud
  poll or treat stale `off` as confident not-charging.
- **Vehicle SOC/raw power unavailable:** inspect the optional EV issue codes. An
  invalid value remains null and cannot make core energy telemetry unhealthy.
- **Home/away unexpected:** compare only the tracker state with `ev_home_state`.
  Coordinates and tracker attributes are intentionally ignored and unavailable in
  the dashboard/API.

## Operational rollback

If the v0.4.0 App cannot collect, prefer an application fallback without a schema
change:

1. Stop the App and disable its automatic start temporarily.
2. Confirm no collector process remains and only one collector will run.
3. On Windows, set `DATABASE_URL` to the production Synology `home_energy` database
   using the appropriate application credential.
4. From the same reviewed v0.4.0 source, run `python tools/run_collector.py`.
5. Confirm new PostgreSQL observations appear at five-minute boundaries.
6. Keep PostgreSQL at `20260811_01` and troubleshoot the App separately.

Do not point production collection back to SQLite. PostgreSQL remains authoritative.
Do not use `alembic stamp` as a rollback.

Rollback to App v0.3.2 requires all collectors stopped and either restoration of the
verified pre-v0.4.0 dump or a tested physical downgrade:

```powershell
.\.venv\Scripts\python.exe -m alembic downgrade 20260810_01
.\.venv\Scripts\python.exe -m alembic current
```

The downgrade removes only the nine nullable EV telemetry columns, so it preserves
legacy rows and fields but discards v0.4.0 EV telemetry. Confirm revision
`20260810_01`, unchanged legacy counts, and absent EV columns before starting
v0.3.2.
