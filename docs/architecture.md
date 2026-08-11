# Phase 1 architecture

The project keeps collection, forecasting, optimisation, and execution as separate
layers. The current read-only phase implements collection, explainable forecasting,
and advisory reserve estimation. It does not contain an executor or device-control
path.

`HomeAssistantClient` performs one allowlisted `GET /api/states` request per
collection. `Collector` parses the selected Amber, Solcast, and GoodWe entities,
evaluates domain-specific health, and creates one timezone-aware
`EnergyObservation` aligned to a five-minute UTC slot. `Historian` persists that
observation through a shared persistence layer backed by SQLite or PostgreSQL.
SQLAlchemy models and Alembic migrations define the portable schema. CLI programs
only assemble these reusable components.

## Production deployment

The production deployment is Home Assistant App v0.4.0 (formerly called an add-on)
on the amd64 Home Assistant OS 18.1 NUC, where it is collecting successfully.
Version 0.4.0 introduced an explicit additive database
migration. Supervisor injects `SUPERVISOR_TOKEN`; the App uses it only as a
bearer token for `http://supervisor/core/api`. The existing GET-only client and
collector are unchanged. Observations are written over the LAN to the external
Synology PostgreSQL 17 `home_energy` database as `energy_app`.

The deployment wrapper copies root-owned `/data/options.json` to a mode-`0600`
ephemeral file during a minimal root bootstrap, then drops to UID/GID 10001 before
Python parses and removes the copy. It constructs one URL-encoded PostgreSQL URL,
performs explicit database revision/readiness and Home Assistant entity checks,
starts one internal watchdog/Ingress web server, then executes the existing five-minute
collector. Supervisor owns boot, watchdog, restart, and shutdown. No cron process,
nested restart loop, SQLite production database, or device-control layer exists in
the App.

Health has independent telemetry, price, solar, and optional weather domains. The
overall display summary currently derives from telemetry because Phase 1 observation
integrity means trustworthy household and inverter measurements, not availability
of every forecast. Price or solar failure remains visible without invalidating an
otherwise useful telemetry observation.

The load profile reads telemetry-healthy observations and groups house power by
local weekday and five-minute slot. A group needs the configured minimum sample
count; otherwise the result explicitly uses the conservative fallback. It is an
explainable mean, not machine learning.

Readiness is consumer-specific: load profiling requires telemetry; future
grid-charge and battery-export recommendations require telemetry, price, and solar.
These readiness checks are advisory gates only and cannot issue commands.

Freshness policies are entity-specific. Live powers use five minutes, SOC and
current Amber prices use ten minutes, Amber forecasts use one hour, and the three
required Solcast summaries use six hours by default. Home Assistant `last_updated`
may remain unchanged for a stable value, so freshness checks are used only for
entities expected to update periodically. Mode, work-mode, and price-spike values
have no freshness penalty.

Power signs are stored exactly as Home Assistant reports them. No charge/discharge,
import/export interpretation is applied until those conventions are measured.

History analysis remains a separate read-only concern. Gap analysis compares stored
UTC slots with an inclusive five-minute sequence. Domain issue analysis reads the
structured health JSON. CSV export selects an inclusive timezone-aware range. The
power-sign validator evaluates all four grid/battery multiplier combinations using
the balance `PV + signed grid + signed battery ≈ house`, alongside battery-mode
groups. It reports residuals and confidence but does not select or persist a sign
convention.

Operational terminal output is intentionally compact by default for a normal-width
Windows console. Detailed issue and load tables are opt-in. Sign validation includes
median residuals and representative low/high-residual examples for every convention,
so a leading hypothesis remains auditable rather than becoming hidden configuration.

Weather entity IDs are optional configuration. When configured, temperature and
condition are collected in the existing bulk GET. Missing weather may make only the
weather domain unhealthy; it cannot affect overall Phase 1 observation health.

Version 0.4.0 adds another optional branch inside the same collection request.
Configured vehicle-cloud entities are reduced to a typed, privacy-minimized
snapshot: SOC, raw vehicle battery power, charging/plugged/online booleans,
at-home boolean, dedicated update time, freshness, source, confidence, status, and
structured optional issues. Missing or stale vehicle data never changes core
telemetry health. Fresh confirmed charging without independently measured charger
AC power preserves measured house load and marks the baseline row ineligible;
plugged-idle remains eligible. No session worker or vehicle API is introduced.

The future executor is deliberately absent. Adding it requires a separate safety
review and explicit approval.

## Read-only presentation layer

Version 0.3.0 extends the existing standard-library health server into one coherent
threaded web application on internal port 8099. The collector remains in the main
thread, uses its original five-minute schedule, and shares only thread-safe health
state with the web layer. Browser requests open short-lived repositories and use
fixed, bounded query methods; a request failure cannot stop or mark the collector
unhealthy.

Supervisor watchdog continues to call `/health`. All dashboard, static, and
`/api/v1` routes require the actual socket peer to be `172.30.32.2`, the Home
Assistant Ingress gateway; loopback is permitted for tests. Forwarded identity and
`X-Forwarded-For` never authorize access. A trusted `X-Ingress-Path` supplies only
the dynamic browser base path.

The local HTML/CSS/vanilla-JavaScript frontend presents existing observations,
forecast runs, request-time read-only comparisons, limited persisted reserve
metadata, and data quality. It creates no forecast, estimator run, entity, command,
or database record. Unsupported mutation HTTP methods return 405.

The collector has an explicit derivation stage after raw parsing. It creates an
`EnergyFlow` only from configured signs, adds optional EV context, calculates a
baseline-load training value, derives cautious event labels, and evaluates a
separate flow-readiness health domain. Overall health continues to follow raw
telemetry rather than derivation readiness.

Forecast storage is independent of collection: immutable runs own period points;
existing CLI comparison may attach local actuals and errors. The v0.3.0 dashboard
uses a separate request-time read-only comparison and never materializes those
values.

The battery reserve estimator is the first advisory consumer of these layers. It
reads the latest stored observation and telemetry-healthy baseline samples, forecasts
household demand until a plausible replenishment window, and calculates held versus
potentially tradable energy. It has no Home Assistant client, executor, or automatic
action path. Its readiness flag means manual review only.

Reserve input selection is explicit. Live mode injects a fresh collector result into
the estimator and does not persist it by default. History mode uses SQLite read-only
queries, supports an as-of upper bound, and exposes observation age. Both modes use
stored baseline history for demand forecasting; current-state provenance is never
implicit.

Demand-history diagnostics are produced before aggregation. All candidate rows are
counted, then exclusions are grouped by telemetry health, baseline-training reason,
missing baseline, or legacy status. Qualified samples still require exact local
weekday and five-minute-slot matching. Configured local-time fallback bands replace
the default flat assumption, while flat mode remains available; neither mode learns
fallback values from sparse data.

Reliability is decomposed into data availability, household-demand forecasting,
opportunity forecasting, and overall reserve confidence. Overall confidence is
capped by demand confidence, which uses history completeness, tier composition,
sample variability and age, EV telemetry, and completed-run error. Training rows
must precede forecast creation, and the current partial local day is excluded from
broad tiers so live and replay results are leakage-safe.

Each reserve CLI run writes only its advisory demand projection to the configured
forecast tables. Completed horizons can be scored against eligible stored
actuals by tier. This analytical feedback path has no executor or Home Assistant
write capability.
