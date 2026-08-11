# Home Assistant App installation

Version `0.3.2` is the pre-migration App. Version `0.4.0` is an unreleased,
schema-changing release candidate for optional read-only vehicle telemetry.

## Publish and install

The repository root contains `repository.yaml` and one App folder,
`home_energy_optimiser/`, so the GitHub repository can be added directly.

Production PostgreSQL must not be migrated until the immutable release has passed
validation and Home Assistant can discover v0.4.0. Follow this order exactly:

1. Complete all source and migration validation.
2. Commit the v0.4.0 release candidate.
3. Push its release branch.
4. Build an image from the exact commit.
5. Run the complete container test against the exact-commit image.
6. Tag and push `v0.4.0`.
7. Build and validate the immutable v0.4.0 tag.
8. Merge or fast-forward the reviewed release to `main`.
9. Refresh the Home Assistant App store and confirm v0.4.0 is offered, but do not
   update yet.
10. Create and restore-test the production PostgreSQL backup.
11. Record exact production application-table counts.
12. Stop v0.3.2 and confirm no other collector is running.
13. Apply `python -m alembic upgrade head` from reviewed v0.4.0 source.
14. Require revision `20260811_01`, application readiness, and unchanged counts.
15. Immediately update and start the already-discoverable v0.4.0 App.
16. Configure the optional BYD entities and validate advancing collection.

The exact backup, migration, count, and validation commands are in
[the vehicle integration runbook](byd_vehicle_integration.md).

Required values (password deliberately omitted):

```yaml
db_host: <Synology LAN DNS name or address>
db_port: 55432
db_name: home_energy
db_user: energy_app
timezone: Australia/Brisbane
health_max_observation_age_seconds: 900
```

Set `db_password` in the App configuration UI. Do not paste it into logs or
documentation. No Home Assistant token is entered; Supervisor supplies one at
runtime.

Optional vehicle values use installation-specific entity IDs; empty strings leave
individual inputs unconfigured:

```yaml
ev_vehicle_enabled: true
ev_charging_entity: <binary_sensor.vehicle_charging>
ev_plugged_entity: <binary_sensor.vehicle_plugged>
ev_online_entity: <binary_sensor.vehicle_online>
ev_soc_entity: <sensor.vehicle_soc>
ev_battery_power_entity: <sensor.vehicle_battery_power>
ev_telemetry_updated_entity: <sensor.vehicle_telemetry_updated>
ev_location_entity: <device_tracker.vehicle_location_state>
ev_home_state: home
ev_telemetry_stale_seconds: 900
```

## First-start verification

1. Confirm startup logs show backend PostgreSQL, the expected host, port, database,
   and username but no password or full URL.
2. Confirm the schema check reports revision `20260811_01` and the read-only Home
   Assistant readiness check passes.
3. Wait through the next clock-aligned five-minute boundary.
4. Confirm a `Saved slot ... No command was issued` log entry appears.
5. From another trusted machine configured with `energy_readonly`, run
   `python tools/check_database.py` and `python tools/inspect_history.py --limit 5`.
6. Confirm the newest PostgreSQL slot advances and there is only one collector.
7. Confirm Watchdog remains enabled and no SQLite database appears in App data.
8. Open **Energy Optimiser** from the Home Assistant sidebar as an administrator.
9. Confirm Overview loads, the read-only badge is visible, nested Ingress assets
   load, and direct port access is not configured.
10. Check History, Forecasts, Reserve, and Data Quality. Sparse forecasts or reserve
    data must show an empty/unavailable state rather than trigger a calculation.

## Updates and local build

Increment `config.yaml` for every App release, point `APP_SOURCE_REF` at the matching
immutable Git tag, push/tag, then use **Update information** in the App store and
install the offered update. Normal updates require no SSH copying.

For an amd64 build test from a committed/pushed ref:

```powershell
docker build --platform linux/amd64 `
  --build-arg APP_SOURCE_REF=<git-tag-or-commit> `
  --build-arg BUILD_VERSION=<version> `
  --tag home-energy-optimiser:<version> `
  home_energy_optimiser
python tools/test_home_assistant_app_container.py `
  --image home-energy-optimiser:<version> --use-image-files
```

The Dockerfile downloads the canonical application source because Supervisor
builds with the App folder as its context; this avoids duplicating collector code
inside the deployment wrapper.

For v0.4.0, follow the immutable-artifact, Home Assistant discovery, backup,
restore-test, count, App-stop, Alembic, immediate-update, plugged-idle, and
active-charging sequence in [the vehicle integration runbook](byd_vehicle_integration.md).
The App must be stopped during the short migration window, and production migration
must not begin before Home Assistant offers the validated v0.4.0 artifact.

## Roll back to v0.3.2

If v0.4.0 fails, first stop the App, keep PostgreSQL at `20260811_01`, and run the
reviewed Windows v0.4.0 collector against production with exactly one collector.
Troubleshoot the App without changing history.

Restore v0.3.2 only after restoring the verified pre-v0.4.0 PostgreSQL dump or after
stopping every collector and running this physical downgrade from reviewed v0.4.0
source:

```powershell
.\.venv\Scripts\python.exe -m alembic downgrade 20260810_01
.\.venv\Scripts\python.exe -m alembic current
```

The downgrade removes only the nine nullable EV telemetry columns, discarding any
EV telemetry collected after v0.4.0 began while preserving legacy fields and row
counts. Require revision `20260810_01`, unchanged legacy counts, and absent EV
columns before starting v0.3.2. Never use `alembic stamp` as a schema rollback.
