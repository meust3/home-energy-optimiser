# Forecast retention

Default policy retains detailed forecast points and scores for 90 days; forecast
run metadata, reserve runs and their opportunity details, and operation attempts
for 365 days; compact daily accuracy rollups indefinitely. Observations, EV
annotations, and derivation audits are never pruned by this service.

Retention is disabled initially. The existing in-process Forecast Operations
coordinator may claim at most one run per UTC date. The original v0.5.1 candidate
performed one 5,000-point transaction per daily claim, so it could not keep up with
the expected 13,824 points and scores created each day. The hardened implementation
keeps 5,000 as the detail transaction size and permits at most six independently
committed batches per invocation: 30,000 expired points and their corresponding
score rows per table per day. Metadata uses separate 500-row bounded transactions.

Every detail transaction writes or updates compact
date/model/alignment/policy/horizon/day-type rollups before deleting that batch. A
rollup or delete failure rolls back only the current batch; earlier committed
batches remain audited and later detail remains intact. The forecast-operation
advisory lock is released before retention begins, so no transaction or database
lock is held between batches. Deadline and shutdown checks occur between batches;
there is no unbounded loop, second scheduler, or same-day retry.

Diagnostics expose eligible, pruned, and remaining rows for both detail tables,
batches executed, batch size, the 30,000-row maximum, the 13,824-row/day estimate,
steady-state capacity health, and estimated backlog-clearance days where capacity
is sufficient. Retention health cannot be healthy when configured/tested capacity
does not exceed the creation estimate. Observations, EV annotations, and derivation
audits are never selected by retention.

Inspect without writes, or explicitly apply one bounded daily maintenance run:

```text
python tools/inspect_forecast_retention.py
python tools/inspect_forecast_retention.py --apply
```

Revision `20260813_01` adds only `forecast_accuracy_rollups` and
`forecast_maintenance_runs`. Physical downgrade to `20260812_01` removes those
tables and their v0.5.1 aggregate/audit data; it does not change observations.

At the default 30-minute schedule, the design creates at most 48 runs and 13,824
points/scores per day. A 90-day steady-state detail window is therefore about
1,244,160 point rows and the same number of score rows before missing/failed runs;
365-day metadata is about 17,520 forecast runs, reserve runs, and operation
attempts each. Actual byte size depends on PostgreSQL JSON/index overhead and must
be measured by `/api/v1/forecast-storage`, not inferred from these row estimates.
