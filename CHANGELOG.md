# Changelog

## 0.5.1

- Fixed scheduled 24-hour forecasts to start on the first full five-minute slot,
  persist `full_5m_v1` alignment provenance, and contain exactly 288 points.
- Added canonical aligned-slot scoring, typed sample-level EV training cohorts,
  deterministic `verified_preferred` selection, and explicit mixed-history risk.
- Added read-only historical EV candidate detection and evaluation-only mean,
  median, trimmed-mean, and winsorized-mean comparison. Production Tier 2 remains
  the arithmetic mean and reserve mathematics are unchanged.
- Added aligned-run calibration metrics/status, reserve calibration warnings,
  residual anomaly visibility, entity-specific staleness states, and dashboard
  calibration/storage views.
- Added bounded tiered retention, permanent daily accuracy rollups, and audited
  daily maintenance. Retention is disabled by default.
- Hardened retention to six independently committed 5,000-row detail batches per
  daily invocation (30,000 rows/table/day), with capacity and backlog diagnostics.
- Isolated Current model calibration by forecast type, model, alignment, and
  training policy; legacy scores remain a separate displayed baseline.
- Persisted scheduled reserve reconciliation for the partial creation-to-aligned-
  start interval without changing reserve or opportunity mathematics.
- Verified existing v0.5.0 option files resolve missing training policy to
  `verified_preferred` and missing retention enablement to `false`; production must
  save both explicitly.
- Added revision `20260813_01`; its physical downgrade removes only v0.5.1
  rollup/maintenance data. Production is already at this revision, so the v0.5.1
  App deployment requires no schema migration. No startup migration or control
  path was added.

## 0.5.0

- Added an opt-in, single-threaded in-process forecast coordinator. It creates
  genuine out-of-sample 24-hour baseline forecasts after aligned boundaries,
  uses durable database claims for restart deduplication, and gives the
  five-minute collector a boundary grace period.
- Added separate immutable forecast-point scoring with delayed actuals,
  availability and health eligibility, missing reasons, absolute/signed/squared
  error, and bounded MAE, bias, RMSE and coverage reporting.
- Added complete advisory reserve snapshots and opportunity evaluations. Every
  result records `command_issued = false`; unavailable tradable energy remains
  `NULL`.
- Added read-only Forecast Operations, Forecast Accuracy and Reserve History
  dashboard/API views and separate non-fatal scheduler health.
- Added additive Alembic revision `20260812_01` with a real downgrade that removes
  only v0.5.0 audit tables. No App startup migration is performed.
- Forecast operations default to disabled. No Home Assistant service, device,
  Modbus, trading or command path was added.
- Preserved the v0.4.1 normalized power-sign configuration, diagnostics, and
  backup-gated historical derived-field repair.

## 0.4.1

- Added validated Home Assistant App options for grid and battery power signs,
  sign confidence, supporting samples, and balance tolerance. Generic defaults
  remain safely unknown and unconfirmed.
- Passed the validated settings into the unchanged collector normalization logic,
  allowing new observations to populate directional grid/battery flow, residual,
  and baseline fields without changing raw telemetry.
- Distinguished normalized-flow gaps caused by unconfigured signs from periods
  with no observations, and exposed the configured signs and confidence on Data
  Quality.
- Tightened historical derived-field repair: dry-run remains the default, writes
  require `--apply --backup-verified`, confirmed rows are protected unless
  `--override-confirmed` is explicit, audit insertion gates updates, and reruns are
  idempotent.
- Preserved raw energy telemetry, BYD fields, EV classifications, manual EV
  annotations, and their baseline decisions during repair. No schema migration,
  Home Assistant write, device command, or energy-balance equation change was
  added.
- This hotfix changes no production schema, forecasting algorithm, Home Assistant
  write surface, or device-control capability.

## 0.4.0

- Added optional, configurable, GET-only vehicle-cloud telemetry for charging,
  plugged, online, SOC, raw vehicle battery power, telemetry freshness, and an
  at-home boolean.
- Added a typed optional EV health/readiness result that cannot make core energy
  telemetry unhealthy or stop collection, persistence, reserve analysis, or the
  dashboard.
- Excluded fresh confirmed charging observations from baseline training when
  direct charger AC power is absent, while preserving measured household load and
  leaving `ev_power_w` null; plugged-idle observations remain eligible.
- Added additive Alembic revision `20260811_01` with nullable, portable
  SQLite/PostgreSQL vehicle columns, a tested physical downgrade that removes only
  those nine columns, and no automatic App migration. Downgrade discards collected
  v0.4.0 EV telemetry while preserving legacy observation fields and counts.
- Added a read-only EV dashboard card, SOC history, state markers, data-quality
  readiness/warnings, API fields, and reserve-page SOC context without changing
  the reserve algorithm.
- Ignored Home Assistant attributes and retained no VIN, coordinates, precise
  location, journey history, or vehicle-control data.
- Retained the strict Home Assistant GET allowlist and added no service call,
  vehicle/charger/inverter command, force poll, Modbus write, or mutation endpoint.
- Released and validated the read-only vehicle telemetry integration on the
  production Home Assistant host.
- Required immutable commit/tag image validation and Home Assistant update
  discovery before production migration. App failure falls back first to the
  reviewed Windows v0.4.0 collector; v0.3.2 requires a physical downgrade or
  verified dump restoration, never an Alembic stamp.

## 0.3.2

- Fixed forecast metadata collapsing into character-by-character vertical text by
  using a stable responsive key/value layout and natural word wrapping.
- Added explicit accessible empty states for wholly missing chart series while
  retaining valid series, single-point markers, and expandable data tables.
- Distinguished reserve fields that are unavailable in a run from fields not
  stored by the current schema, with a clearer schema-coverage notice.
- Replaced repeated unavailable directional-flow pills with one concise summary
  and made unavailable live metrics informational rather than dominant.
- Standardized dashboard spacing, card sizing, table overflow, and desktop,
  tablet, and narrow-screen layouts.
- Made no API, collector, database, forecast, reserve-estimation, security,
  Ingress, Home Assistant service, or device-control changes.

## 0.3.1

- Added the Home Assistant App's detailed App-page documentation and user-facing
  package changelog.
- Updated the Home Assistant image type label from the legacy `addon` value to
  `app`.
- Made no dashboard, API, collector, database, forecast, reserve, security,
  Ingress, Home Assistant service, or device-control changes.

## 0.3.0

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

Versions 0.3.0 and 0.3.1 were not installed on the production Home Assistant OS
NUC. Version 0.3.2 subsequently superseded their App package.

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
