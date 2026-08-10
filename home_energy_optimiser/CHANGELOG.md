# Changelog

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
