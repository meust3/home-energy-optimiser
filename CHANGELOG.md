# Changelog

## 0.8.6 - reconciled App update

- Publishes reconciled data-quality, diagnostic and optional offline review work.
- Preserves running schema `20261024_01`; no live migration from v0.8.5.
- Standard builds omit the SDK. Live integrations, hardware controls, operational
  non-HOLD selection and retention remain disabled. Preserve protected options.
- Corrects the release baseline using the verified 25 October v0.8.5 acceptance.
- See [deployment and rollback](docs/Testing/v086_deployment_20261031.md).

## 0.8.5 historical preparation notes (superseded)

The 31 October live preflight and retained 25 October acceptance establish that
v0.8.5 was already deployed. Migration instructions below apply only to the old
v0.8.4-to-v0.8.5 transition, not the v0.8.6 update.

- Reconciles data-quality reporting, elapsed forecast actuals, bounded observation
  batching and collection diagnostics while retaining main's indexed scoring,
  transaction guarantees, model policy and existing release configuration.
- Includes optional AI review/SDK support and standalone SEMS/Jev tooling; the
  standard App omits the SDK and no live capability is activated by installation.
- Deployment preparation and isolated retained-backup rehearsal are documented in
  [the v0.8.5 runbook](docs/Testing/v085_deployment_preparation_20261031.md).

- Replaces repeated historical pending-score scans with the transactional indexed
  inventory from PR #19; preserves issued forecasts, scoring/EV rules and models.
- Requires explicit migration `20261008_01` -> `20261024_01`; no startup migration.
  Upgrade/downgrade, role permissions, inventory reconciliation and rollback need
  an isolated current-data rehearsal before a separately approved live cutover.
- Includes the previously merged offline readiness/fake-pilot preparation below.
  No live transport, hardware authorization, operational non-HOLD or retention
  setting is enabled by preparing this candidate.
- Candidate preparation is not publication, deployment or production acceptance.
  The installed v0.8.4 baseline and sealed evidence remain unchanged.

## Previously merged software-only controlled-test readiness review

- Adds an explicit offline preservation-test checklist and read-only field reviewer.
  Unknown limits, recovery and credential disposition remain unresolved. A complete
  input record still grants no hardware authority and provisions no transport.
- Rejects malformed recovery alternatives even when another route is verified.
  Review times normalize to UTC once; unrepresentable offset conversions produce
  structured refusal. Annotated regression tests cover both review findings.
- Retains known cumulative fake delivery across missing samples and restart; adds
  regression coverage for this gap and failed-return ownership across restart.
- Reconciles release documentation with dated v0.8.4 acceptance evidence. These
  software changes do not deploy an App, change options or activate hardware.
  CI build validation is distinct from installed runtime evidence.
- Requires explicit service-health feedback and enforces preservation import-cost
  bounds, including return verification. Public examples omit private site/task
  metadata; owner records and sealed evidence remain unchanged.

## 0.8.4 - 2026-10-17 - SOC capture freshness

- New optional captures pin versioned GoodWe runtime clock and HA receipt evidence
  for unchanged SOC values. Research admission validates both within the existing
  600-second bound, with source/slot/value binding and fail-closed invalid evidence.
- Preserves historical capture interpretation and hashes, existing research profile,
  forecasts, reserve and terminal rules. Adds no requests, workers or device writes.
- No migration or option change. Hardware execution remains disabled.
- Publication/update and initial acceptance completed at exact commit
  `72a446cf28abb89217d76030004d6829b1c3007e`. Independent installed-byte attestation
  remains unverified under the approved amendment. See
  [acceptance summary](docs/Testing/v084_production_acceptance_20261017.md).

Older candidate headings below retain their historical preparation-stage labels;
they do not describe the current installed release or establish publication status.

## 0.8.3 - scoring reliability candidate (not published)

- Selects pending forecast scores in bounded ID ranges while preserving oldest-first
  order, existing eligibility rules and transactional rollback.
- Records safe scoring subphase timings, counts and SQLSTATE without SQL parameters,
  credentials or household payloads.
- Uses a consistent PostgreSQL scoring snapshot and a bounded selection budget.
  Smaller individual queries require more round trips; total work is not eliminated.
- Constrains runtime dependency resolution to the retained v0.8.2 package baseline.
- No forecast-model, solar, reserve, profile, dependency, migration, retention or
  hardware-control change. Historical scores and captures are not rewritten.

## 0.8.1 - local advisory input compatibility candidate (not published)

- Adds an opt-in versioned conditional interpretation of attributable Amber
  boundary-plus-one-second decision prices; original captures and strict generic
  coverage/outcome rules remain unchanged.
- Adds explicit fixed-floor and exact linked capacity-capped reserve modes. Each
  linked floor is frozen from its witnessed input snapshot, with no fallback.
- Exposes conditional price, reserve and zero-additional-EV assumptions in the
  GET-only research display. A full-capacity floor permits no model discharge.
- No migration, dependency/default, reserve-engine, selector, hardware or
  retention change. Profile remains empty and capture defaults off.

## 0.8.0 - local arbitrage programme candidate (not published)

- Adds immutable, optional already-fetched input capture and commit witnesses,
  a portable frozen R/P/G research pipeline and GET-only Arbitrage dashboard.
- Adds separately versioned operational/terminal/sequential/export diagnostics
  and a durable fake-only disabled executor; no physical transport or API.
- Requires manual additive schema 20261008_01; compatible disabled recovery
  preserves evidence. Older code rejects the new head; downgrade deletes it.
- Capture defaults off, profile empty; installed limits/EV/PV/price availability
  are not invented. Original studies and outcome-v2 semantics remain unchanged.
- Local source-only preparation; publication/deployment and all hardware
  action families need their separately named gates. See docs/arbitrage/PROGRAMME.md.

## 0.7.0 - release candidate (not published)

- Adds optional mapped indoor/current-weather context collection and immutable
  archived weather snapshots. Collection is disabled by default and the mapping
  is empty until separately approved activation.
- Reuses Met.no through existing Home Assistant states. The corrected hourly HA
  cache is a separate HA-side setup; Energy remains GET-only. Failed/restored or
  oversized cache payloads stay unavailable and retain prior attributes honestly.
- Requires manual migration 20260927_01 -> 20261005_01 even with context disabled.
  Adds only context_observations and weather_context_snapshots; startup never
  migrates. Original records/calculations are not rewritten and forecasts do not
  consume the new context yet.
- v0.6.5 rejects the new schema. Tested compatible code with context disabled is
  the non-destructive recovery path for the supported scenario; physical downgrade
  deletes context/weather history and requires separate explicit approval. See
  docs/forecast_context_collection.md and the final local runtime report.
- No physical outdoor sensor or metered HVAC power is implied by the initial
  mapping. Forecast models, calibration, reserves, shadow policy, non-HOLD gates,
  AI routing, retention and outcome-v2 comparative nulls remain unchanged.

## 0.6.5 - release candidate (not published)

- Assembles complete action-window household demand from compatible linked
  prealignment reserve intervals and aligned operational forecast intervals,
  without double counting, reserve EV demand or filling later forecast gaps.
- Separates signed HOLD reserve margin from nonnegative available energy; unknown
  values remain unavailable and a shortfall does not prevent no-command HOLD.
- Applies the existing one-second price-gap tolerance to each internal boundary;
  endpoints stay strict and prices retain represented-duration weighting.
- Marks new calculations `battery-shadow-evidence-v2`. Dashboard and replay retain
  explicit legacy semantics and label unknown calculation semantics unavailable.
- No historical recalculation, schema migration or new decision authority.
  Policy, assumptions, physical limits and HOLD-only gates are unchanged.
  Outcome-v2 selected-versus-HOLD, hindsight, regret and simulated reserve safety
  remain unavailable. Corrected inputs may change future diagnostic values.

## 0.6.4 - 2026-10-03

- Retains allowlisted Solcast half-hour P10/P50/P90 power forecasts in existing
  observation JSON for time-based recharge analysis; no schema migration.
- Adds an explicit offline morning-export planner and replay tool with linked
  reserve, calibration, power, recharge and economic gates. No scheduled activation.
- Keeps HOLD-only production recommendations, retention disabled, and GET-only
  hardware access. The reserve estimator is unchanged; hardware controls remain absent.
- Historical snapshots without interval solar or export/discharge limits remain
  blocked; model comparisons are not measured savings.

## 0.6.1 - 2026-09-12

- Correct outcome accounting to integrate paired slot energy/prices and partial
  action-window overlaps; incomplete totals remain NULL.
- Introduce append-only `battery-shadow-outcome-v2`; leave HOLD comparisons,
  hindsight, regret and simulated reserve safety unavailable until a validated
  counterfactual model exists. Legacy v1 evidence remains unchanged.
- Show corrected observed outcomes and explicit legacy limitations in the dashboard.
- No schema, decision policy, recommendation defaults or hardware access change.

## 0.6.0 - 2026-09-05

- Added an opt-in deterministic battery-only shadow engine inside the existing
  Forecast Operations coordinator. It persists candidate evidence only after the
  linked forecast and reserve, defaults to HOLD-only, and cannot issue commands.
- Added assumption/policy versioning, fail-closed calibration, freshness, price,
  reserve and constraint gates, duration-overlap Amber economics, and explicitly
  blocked EV capabilities.
- Added additive revision `20260905_01` for immutable decision runs/candidates and
  append-only outcome versions. The database enforces `no_command_issued = true`.
- Added delayed simulated outcome comparison against HOLD and hindsight, with
  coverage, reserve-breach, counterfactual and probable-intervention disclosures.
- Fixed exact-identity calibration-rollup backfill planning and normalized Solcast
  P10/P50/P90 diagnostic keys without changing forecast or reserve arithmetic.
- Added GET-only Decisions APIs/dashboard, an accessible Overview Forecast vs
  Actual card, and a read-only synthetic replay tool.
- No Home Assistant service, device, Modbus, EV, SEMS, trading, retention, forecast
  hierarchy, reserve arithmetic, or automatic solar-derating path was added.

## 0.5.2

- Calibration readiness now uses the exact forecast identity and independent
  local-date evidence. Overlapping forecasts are averaged once per target slot
  and horizon; raw row-weighted metrics remain visible separately.
- Added WAPE, signed daily energy error, and median/P90/P95 cumulative
  underforecast diagnostics. Seven 95%-complete dates, weekday/weekend evidence,
  and all four horizon buckets are required before calibration can be acceptable.
- `tradable_energy_is_calibrated` now also requires the reserve row's linked
  forecast identity, complete independent evidence, and no quality blocks.
- Added additive Alembic revision `20260814_01`, extending the existing accuracy
  rollup table. Its physical downgrade removes only v0.5.2 aggregate fields.
- Materially negative household demand (below -1 W) remains stored raw but is
  telemetry-invalid, baseline-ineligible, and excluded consistently from scores.
  Added a dry-run-default, backup-gated historical reclassification tool.
- Added GET-only daily Solcast P10/P50/P90 versus realised-PV diagnostics with
  cautious battery/export/clipping context. No curtailment claim or automatic
  solar derating is made.
- Retention remains disabled and now fails closed unless durable rollup coverage
  already represents the candidate detail rows.
- No forecast hierarchy, Tier 2 mean, reserve arithmetic, collector cadence,
  Home Assistant writes, device commands, or execution paths changed.

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
