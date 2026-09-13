# Changelog

## 0.6.2 - 2026-09-13

- Shows all persisted forecast points even when actuals are missing, and rebuilds
  the dated time axis for the selected horizon. Preserves run selection on refresh.
- Excludes unhealthy and baseline-ineligible actuals from baseline comparisons,
  including known charging without measured charger AC power. Reports exclusions.
- Preserves genuine forecast errors, stored evidence, model and scoring policies.
- Uses revision `20260905_01`; no migration from v0.6.1. HOLD-only and retention
  settings remain unchanged; no hardware-control path is added.

## 0.6.1 - 2026-09-12

- Corrects observed outcome value using paired slot energy/prices and partial
  interval overlap; missing or invalid data leaves whole-window totals unavailable.
- Appends scoring v2 without changing original decisions or legacy v1 outcomes.
- Withholds unsupported HOLD comparisons, hindsight, regret and simulated reserve
  safety until a counterfactual model is validated; labels legacy dashboard values.
- Requires the existing revision `20260905_01`; no migration from v0.6.0.
- Keeps the existing coordinator, HOLD-only recommendation gate and retention
  defaults. No device command or Home Assistant write path is added.

## 0.6.0 - 2026-09-05

- Adds opt-in, HOLD-only-by-default battery shadow decisions after linked forecast
  and reserve persistence in the existing coordinator.
- Adds immutable candidate evidence, append-only simulated outcomes, exact
  calibration/rollup gates, and database-enforced no-command records.
- Adds bounded GET-only Decisions and Forecast vs Actual views plus safe health
  and progress status.
- Requires manual additive revision `20260905_01`. The App performs no migration,
  retention, Home Assistant service call, device command, or trade.

## 0.5.2

- Uses independent date/horizon calibration rollups and conservative linked-run
  tradable gating.
- Rejects materially negative household demand from derived training/scoring
  while preserving raw telemetry.
- Adds read-only Solcast-versus-realised-PV diagnostics.
- Requires Alembic revision `20260814_01`; retention remains disabled.

## 0.5.1

- Corrected operational forecasts to 288 aligned five-minute slots.
- Added EV-aware training provenance, calibration/storage visibility, and
  disabled-by-default bounded retention.
- Hardened daily retention to 30,000 detail rows per table in short batches,
  isolated current-model calibration cohorts, and persisted reserve alignment-gap
  reconciliation. Existing installs keep retention off by runtime default.
- Requires Alembic revision `20260813_01`; production is already at this revision,
  so this App update needs no schema migration. No startup migration or Home
  Assistant/device write path was added.

## 0.5.0

- Adds opt-in scheduled Forecast Operations with genuine out-of-sample forecasts,
  delayed scoring, and complete advisory reserve audit persistence while retaining
  one collector and one application process.
- Adds bounded GET-only Forecast Operations, Forecast Accuracy and Reserve
  History views. There are no run-now or mutation routes.
- Requires explicit Alembic revision `20260812_01` before App update. The App
  never migrates PostgreSQL on startup and scheduled Forecast Operations remain
  disabled by default.
- Keeps UID/GID 10001, Supervisor watchdog behaviour, PostgreSQL fail-closed
  startup and the strict read-only hardware boundary.
- Preserves the v0.4.1 normalized power-sign configuration, diagnostics, and
  backup-gated historical repair.
- Adds no Home Assistant write or device-control capability.

## 0.4.1

- Added validated App options for grid/battery signs, confidence, supporting
  samples, and balance tolerance, with unknown/unconfirmed safe defaults.
- Enabled the existing collector to derive normalized grid and battery directions
  for new observations when signs are explicitly configured.
- Added a clear unconfigured-sign empty state and current sign configuration on
  Data Quality.
- Added backup-gated, audited, idempotent historical flow repair that protects
  confirmed rows and preserves raw, BYD, EV, and manual-annotation data.
- Added no database migration, forecasting change, Home Assistant write, or
  device-control path.

## 0.4.0

- Added optional read-only vehicle charging, plugged, online, SOC, home/away, and
  freshness telemetry configured through App options.
- Added a vehicle status card, SOC history, state markers, reserve context, and EV
  data-quality warnings without adding controls.
- Excluded fresh confirmed charging from household baseline learning when direct
  charger AC power is unavailable; measured house load remains unchanged and no EV
  power is invented.
- Stored vehicle battery power only as explicitly labelled raw vehicle-side data,
  never as charger AC demand.
- Requires additive database migration `20260811_01` before App update; migration
  remains an explicit operator step and is not run at startup.
- Retained GET-only Home Assistant access, UID/GID 10001 runtime, protected App
  options, PostgreSQL fail-closed startup, and no device-control path.
- This package was subsequently validated on the production Home Assistant OS
  host.

## 0.3.2

- Fixed forecast metadata wrapping and introduced a stable responsive key/value
  layout.
- Added intentional empty states for missing grid and battery chart data while
  retaining accessible tables and any valid series.
- Distinguished reserve fields that are unavailable in a run from fields not
  stored by the current schema.
- Replaced repeated unavailable directional-flow labels with one concise note and
  improved card, table, desktop, tablet, and narrow-screen layouts.
- Retained local HTML, CSS, JavaScript, and SVG assets with no analytics or
  external frontend dependencies.
- Made no API, collector, database, forecast, reserve-estimation, security,
  Ingress, Home Assistant service, or device-control changes.

## 0.3.1

- Added detailed App-page documentation and an App-local user-facing changelog.
- Updated the Home Assistant image metadata to use the current `app` type label.
- Made no dashboard, API, collector, database, forecast, reserve, security,
  Ingress, Home Assistant service, or device-control changes.

## 0.3.0

- Added an administrator-only Home Assistant Ingress dashboard with Overview,
  History, Forecasts, Reserve, and Data Quality views.
- Added a bounded GET-only dashboard API.
- Added local HTML, CSS, JavaScript, and SVG charts with no external frontend
  assets or analytics.
- Displays existing stored forecasts and reserve estimates only; it does not add
  a forecast scheduler or change forecasting algorithms.
- Made no database schema changes, Home Assistant service calls, or device-control
  changes.

## 0.2.1

- Fixed access to Supervisor's root-owned mode-0600 options file.
- Retained the unprivileged UID/GID 10001 application runtime.
- Made no collector or database behaviour changes.

## 0.2.0

- Added the initial Home Assistant App collector deployment.
- Added external PostgreSQL support and Supervisor Core API authentication.
- Kept collection strictly read-only.
