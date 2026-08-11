# Forecast operations

Version 0.5.0 is an unreleased, strictly advisory release candidate. Forecast
operations are disabled by default and run inside the existing Home Assistant App
Python process. There is no second container, collector, worker pool or cron daemon.

## Scheduling and collector priority

The coordinator calculates aligned wall-clock boundaries in the configured timezone
(`Australia/Brisbane` by default), stores UTC timestamps, and waits a 20-second
collector grace period before beginning analysis. The five-minute collector remains
the primary workload. Forecast work uses short transactions only and never waits in
an open transaction.

Each boundary is claimed by a unique `(operation, scheduled_for_utc)` database key.
This durable claim prevents duplicate creation after restart and also acts as the
SQLite-compatible single-run guard. A process lock prevents in-process overlap.
Stale `running` attempts older than the configured runtime are marked failed on
restart rather than replayed. Attempts record running, success, failure or skipped
state, timestamps, duration, output IDs, point count and a bounded secret-safe
failure class.

The coordinator has one cooperative execution path and checks its runtime deadline
between forecast creation, scoring and reserve persistence. Failures are contained,
reported separately from collection health and retried only at a later aligned
boundary. Scheduler-only PostgreSQL connections use a 10-second connect timeout and
at most a 30-second statement/lock timeout; scoring checks the overall deadline
between points. The wait uses an event, and the daemon coordinator cannot hold the
process open after the bounded graceful join during shutdown.

## Forecast creation

Each scheduled run calls the existing household-demand hierarchy without changing
its tiers or fallback rules. The input query ends at the run creation timestamp;
the existing forecaster also rejects same/future samples. The default horizon is 24
hours from creation. Every five-minute point stores expected power, nullable bounds,
tier, sample count, variability and source explanation. Run metadata stores the
model version, configuration/input summary, confidence and
`run_kind=genuine_out_of_sample`.

Forecast values are immutable. Completed actuals and errors live in
`forecast_point_scores`. No historical runs are reconstructed and represented as
genuine scheduled forecasts; a future replay facility must use an explicit replay
label.

## Options

```yaml
forecast_operations_enabled: false
forecast_interval_minutes: 30
forecast_horizon_hours: 24
forecast_alignment_minutes: 30
forecast_scoring_delay_minutes: 10
forecast_max_runtime_seconds: 120
reserve_snapshot_enabled: true
```

Intervals are bounded to 15–1440 minutes and must be a multiple of the validated
alignment. Horizons are 1–168 hours, scoring delays 0–1440 minutes, and runtime
limits 30–900 seconds. Enabling reserve snapshots has no effect while forecast
operations remain disabled.

No option is returned through the API, and failure summaries never contain raw
options, database URLs, tokens or exception messages.
