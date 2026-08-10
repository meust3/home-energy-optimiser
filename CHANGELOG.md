# Changelog

## 0.3.0 release candidate (Unreleased)

- Added an experimental, administrator-only Home Assistant Ingress dashboard with
  live energy overview, historical charts, persisted forecast-versus-actual views,
  persisted reserve summaries, and collection data-quality reporting.
- Added a versioned, typed, GET-only dashboard API with bounded time ranges,
  server-side aggregation, explicit units, UTC timestamps, truthful nulls, and
  secret-safe errors.
- Restricted dashboard, API, and static routes to the actual Ingress gateway peer
  (plus loopback for tests); kept `/health` available to Supervisor watchdog and
  added local-only security headers and dynamic Ingress-prefix handling.
- Added responsive, accessible HTML/CSS/vanilla-JavaScript assets with no external
  fonts, analytics, CDN, frontend build pipeline, or third-party chart dependency.
- Preserved the existing one-process, one-collector runtime, PostgreSQL fail-closed
  startup, UID/GID 10001 privilege drop, signal handling, and options-file cleanup.
- Made no household-demand, confidence-tier, reserve-estimation, database-schema,
  Home Assistant entity, forecast-worker, scheduler, or device-control changes.

Version 0.3.0 remains a release candidate until built, installed, and verified on
the production Home Assistant OS NUC.

## 0.2.1

- Fixed access to Supervisor's root-owned `0600` options file by copying it into a
  mode-`0600` ephemeral runtime location during a narrowly scoped root bootstrap.
- Kept the Python application, collector, and health server at UID/GID 10001 after
  bootstrap; collector, database, forecast, and read-only behaviour are unchanged.
- Added a portable SQLite/PostgreSQL persistence architecture and completed the
  application-wide repository refactor.
- Added production PostgreSQL cutover, adoption, validation, backup, and recovery
  support.
- Improved reserve forecasting with deterministic replay, explicit forecast
  horizons, sequential replenishment evaluation, and stronger safety invariants.
- Added Home Assistant App release-candidate packaging for an external PostgreSQL
  database and Supervisor-proxied read-only Home Assistant access.
- Hardened credential redaction, ignored-file coverage, Docker build context, and
  non-root container execution.
- Expanded architecture, database, deployment, troubleshooting, security, and
  multi-platform operational documentation.
