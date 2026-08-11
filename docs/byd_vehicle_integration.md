# Read-only vehicle telemetry integration

Version 0.4.0 is operational with optional, read-only vehicle telemetry. The
implementation is designed around the states exposed by a
BYD vehicle cloud integration, but every Home Assistant entity ID is
installation-specific configuration. No product-specific entity ID is a universal
default.

## Supported state classes

Configure only the entities available in the installation, using placeholders such
as:

```text
<binary_sensor.vehicle_charging>
<binary_sensor.vehicle_plugged>
<binary_sensor.vehicle_online>
<sensor.vehicle_soc>
<sensor.vehicle_battery_power>
<sensor.vehicle_telemetry_updated>
<device_tracker.vehicle_location_state>
```

The collector reads them in its existing bulk `GET /api/states` request. It does
not call a vehicle API, change the integration polling interval, or invoke a force
poll. Disabled, incomplete, missing, stale, malformed, and offline vehicle data are
optional warnings and cannot make core energy telemetry unhealthy.

## State semantics

- Charging `on` is confirmed only while the dedicated telemetry timestamp is
  fresh. Charging `off` becomes confident only while fresh and online, or while
  fresh when no online entity is configured. Stale or unavailable `off` is
  unknown, not false.
- Plugged and charging are separate states. Fresh telemetry can therefore report
  charging, plugged-idle, home-unplugged, away, offline, stale, or unknown.
- SOC is retained only in the inclusive range 0-100%. Invalid values become null
  and create an optional `ev_soc_invalid` issue.
- The dedicated telemetry timestamp is normalized to UTC. Age and freshness use
  the configured threshold, 900 seconds by default.
- The tracker state is compared with the configured home-state value and reduced
  to `true`, `false`, or null. Coordinates and tracker attributes are ignored.

## Raw battery power is not charger AC power

`ev_vehicle_battery_power_w_raw` is vehicle-side cloud telemetry. Its sign
convention, measurement point, sampling behavior, and relationship to AC input and
charging losses have not been validated. It is never copied to `ev_power_w`, used
to infer charging, subtracted from household consumption, or presented as charger
AC demand.

When fresh vehicle telemetry confirms charging and no direct AC charger power is
available, measured `house_consumption_w` is preserved, `ev_power_w` remains null,
and the observation is excluded from baseline training with
`known_ev_session_without_ac_power`. Fresh plugged-idle observations remain
eligible when all existing core telemetry rules pass. Automatic session grouping
is deferred; historical charging intervals are identifiable from per-observation
charging state without restart-sensitive state.

## Privacy and safety

The schema and API retain only SOC, raw battery power, charging/plugged/online
booleans, at-home boolean, freshness fields, status, source, and confidence. They do
not retain or expose VIN, latitude, longitude, exact home coordinates, GPS history,
journey history, lock, door, window, climate, schedule, or full Home Assistant
attributes.

The Home Assistant client remains limited to `GET /api/`, `GET /api/states`, and
`GET /api/states/<entity_id>`. There is no Home Assistant service call, vehicle or
charger command, polling command, inverter write, or Modbus path. Dashboard and API
routes remain GET-only.

## Configuration

Home Assistant App options use empty entity values as unconfigured:

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

Windows/local equivalents are `EV_VEHICLE_ENABLED`, `EV_CHARGING_ENTITY`,
`EV_PLUGGED_ENTITY`, `EV_ONLINE_ENTITY`, `EV_SOC_ENTITY`,
`EV_BATTERY_POWER_ENTITY`, `EV_TELEMETRY_UPDATED_ENTITY`, `EV_LOCATION_ENTITY`,
`EV_HOME_STATE`, and `EV_TELEMETRY_STALE_SECONDS`.

## Production migration and update order

Version 0.4.0 requires Alembic revision `20260811_01`. It is additive and leaves
legacy rows null. The App never runs it automatically.

Production schema migration must not occur until the immutable v0.4.0 release
artifact has passed validation and Home Assistant can discover the offered update.
The required order is:

1. Complete source, migration, privacy, and container validation.
2. Commit the v0.4.0 release.
3. Push its release branch.
4. Build an image from that exact commit.
5. Run the complete container test against that exact-commit image.
6. Tag and push `v0.4.0`.
7. Build and validate the immutable v0.4.0 tag.
8. Merge or fast-forward the reviewed release to `main`.
9. Refresh the Home Assistant App store and confirm v0.4.0 is offered, but do not
   update the App yet.
10. Before the v0.4.0 migration, while v0.3.2 remained running, create and
   restore-test the production PostgreSQL backup from a trusted workstation:

   ```powershell
   pg_dump --format=custom --file home_energy_pre_v0.4.0.dump --dbname home_energy
   pg_restore --list home_energy_pre_v0.4.0.dump | Out-File home_energy_pre_v0.4.0.contents.txt
   if (-not (Select-String -Path home_energy_pre_v0.4.0.contents.txt -Pattern "TABLE DATA public observations" -Quiet)) { throw "Verified dump does not contain observations table data" }
   createdb home_energy_v040_restore_test
   pg_restore --clean --if-exists --no-owner --no-privileges --dbname home_energy_v040_restore_test home_energy_pre_v0.4.0.dump
   psql --dbname home_energy_v040_restore_test --command "SELECT COUNT(*) AS restored_observations FROM observations;"
   ```

   Supply connection details through protected environment/client configuration;
   do not place a password in shell history. Keep the explicitly named temporary
   restore database until the next count-comparison step succeeds.
11. Record exact production counts for `observations`, `forecast_runs`,
   `forecast_points`, `observation_derivations`, `ev_session_annotations`,
   `ev_session_annotation_rows`, and `migration_progress`:

   ```powershell
   $countSql = "SELECT (SELECT COUNT(*) FROM observations) AS observations, (SELECT COUNT(*) FROM forecast_runs) AS forecast_runs, (SELECT COUNT(*) FROM forecast_points) AS forecast_points, (SELECT COUNT(*) FROM observation_derivations) AS observation_derivations, (SELECT COUNT(*) FROM ev_session_annotations) AS ev_session_annotations, (SELECT COUNT(*) FROM ev_session_annotation_rows) AS ev_session_annotation_rows, (SELECT COUNT(*) FROM migration_progress) AS migration_progress;"
   $productionCounts = (psql --dbname home_energy --csv --tuples-only --command $countSql | Out-String).Trim()
   $restoredCounts = (psql --dbname home_energy_v040_restore_test --csv --tuples-only --command $countSql | Out-String).Trim()
   if ($productionCounts -ne $restoredCounts) { throw "Restore-test table counts do not match production" }
   $productionCounts
   dropdb home_energy_v040_restore_test
   ```
12. Stop the v0.3.2 Home Assistant App and confirm no Windows or other collector is
    running.
13. In the reviewed immutable v0.4.0 source, set `DATABASE_URL` for the authorized
    migration role and run:

   ```powershell
   .\.venv\Scripts\python.exe -m alembic upgrade head
   .\.venv\Scripts\python.exe -m alembic current
   .\.venv\Scripts\python.exe tools\check_database.py --application-readiness
   ```
14. Require revision `20260811_01`, repeat every recorded count, and require every
    value to be unchanged:

    ```powershell
    $afterCounts = (psql --dbname home_energy --csv --tuples-only --command $countSql | Out-String).Trim()
    if ($afterCounts -ne $productionCounts) { throw "Production table counts changed during migration" }
    ```
15. Immediately update and start the already-discoverable v0.4.0 App.
16. Configure the optional vehicle entity IDs and confirm exactly one collector and
    an advancing five-minute slot.

## First-state verification

For a fresh plugged-idle observation, confirm: at-home is the expected boolean;
plugged is true; charging is false; SOC and telemetry age are plausible;
`baseline_training_eligible` remains true; raw battery power is labelled raw; and
`ev_power_w` remains null.

During the next real charging session, confirm: charging is true only with fresh
telemetry; the row source/confidence are `byd_vehicle_cloud`/`direct_fresh`;
`house_consumption_w` is unchanged; `ev_power_w` remains null; baseline eligibility
is false with `known_ev_session_without_ac_power`; and no command or service call
appears in logs.

## Rollback

The preferred fallback after an App failure is not a schema rollback. Stop the
failed v0.4.0 App, keep production PostgreSQL at `20260811_01`, and run the reviewed
v0.4.0 Windows collector against that database. Maintain exactly one collector and
troubleshoot the App without altering production history.

Roll back to App v0.3.2 only when the maintenance window permits a physical schema
downgrade or when restoring the verified pre-v0.4.0 dump. Stop every collector,
take another verified backup if v0.4.0 collected useful data, and run from the exact
v0.4.0 source:

```powershell
.\.venv\Scripts\python.exe -m alembic downgrade 20260810_01
.\.venv\Scripts\python.exe -m alembic current
```

The downgrade removes only the nine nullable v0.4.0 EV telemetry columns. It
preserves legacy fields and rows, but permanently discards EV telemetry stored in
those columns after v0.4.0 began. Require revision `20260810_01`, unchanged legacy
counts, and absence of all nine EV columns before starting v0.3.2. Verify absence
with:

```powershell
psql --dbname home_energy --command "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='observations' AND column_name IN ('ev_vehicle_soc_percent','ev_vehicle_battery_power_w_raw','ev_plugged_in','ev_vehicle_online','ev_at_home','ev_telemetry_updated_at_utc','ev_telemetry_age_seconds','ev_telemetry_fresh','ev_vehicle_status') ORDER BY column_name;"
```

The query must return no rows. Never use `alembic stamp` as a schema rollback.

To retry v0.4.0, stop v0.3.2, run `alembic upgrade head`, verify `20260811_01` and
unchanged legacy counts, then start v0.4.0. Alternatively, restore the verified
pre-v0.4.0 dump and verify its revision and counts before starting v0.3.2.

EV energy separation remains incomplete until independently measured charger AC
power is integrated and validated. Vehicle SOC is dashboard context only; no EV
battery capacity, target SOC, or ready-by requirement enters reserve estimation.
