# Changelog

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
- This package is not yet released or verified on the production Home Assistant
  OS host.

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
