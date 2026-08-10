# Phase 1 architecture

The project keeps collection, forecasting, optimisation, and execution as separate
layers. Phase 1 implements only read-only collection and a basic historical load
profile. It does not contain an optimiser or executor.

`HomeAssistantClient` performs one allowlisted `GET /api/states` request per
collection. `Collector` parses the selected Amber, Solcast, and GoodWe entities,
evaluates domain-specific health, and creates one timezone-aware
`EnergyObservation` aligned to a five-minute UTC slot. `Historian` persists that
observation through a shared persistence layer backed by SQLite or PostgreSQL.
SQLAlchemy models and Alembic migrations define the portable schema. CLI programs
only assemble these reusable components.

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

The future executor is deliberately absent. Adding it requires a separate safety
review and explicit approval.

The collector has an explicit derivation stage after raw parsing. It creates an
`EnergyFlow` only from configured signs, adds optional EV context, calculates a
baseline-load training value, derives cautious event labels, and evaluates a
separate flow-readiness health domain. Overall health continues to follow raw
telemetry rather than derivation readiness.

Forecast storage is independent of collection: immutable runs own period points;
later comparison attaches local actuals and errors. These tables support future
projected-vs-actual dashboards without implementing a dashboard or optimiser.

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

Each reserve CLI run writes only its advisory demand projection to the existing
local forecast tables. Completed horizons can be scored against eligible stored
actuals by tier. This analytical feedback path has no executor or Home Assistant
write capability.
