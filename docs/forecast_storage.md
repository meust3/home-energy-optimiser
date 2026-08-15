# Forecast-series storage

v0.5.1 adds compact daily accuracy rollups and audited maintenance at revision
`20260813_01`; see [forecast_retention.md](forecast_retention.md). New run metadata
includes model/alignment versions, policy, cohort composition, and contamination
risk. Legacy rows remain immutable.

Version 0.5.0 adds genuine scheduled `baseline_household_load` runs with source
`scheduled_forecast_operations`. Their creation/horizon/model/input metadata and
point values are immutable. Delayed actuals and errors are written only to
`forecast_point_scores`; missing and unhealthy actuals remain explicitly unscored.
See `forecast_operations.md` and `forecast_scoring.md`.

`forecast_runs` identifies a forecast production event: type, source, model version,
creation time, horizon, and metadata. `forecast_points` contains expected,
lower/upper, unit, actual, and error values for each period.

Comparison maps forecast type to a stored actual field and calculates `error =
actual - expected`. Run metrics report mean absolute error and signed bias. Missing
actuals remain NULL and do not count toward metrics.

Supported types are solar power, household and baseline load, battery SOC, grid
import/export, and buy/sell prices.

## v0.5.0 storage-growth risk

`FORECAST_RETENTION_DAYS` is parsed into collector configuration, but v0.5.0 does
not apply it to scheduled forecast rows. Automatic deletion is intentionally absent
from this release. At the default 30-minute cadence and 24-hour horizon, 48 runs per
day each store 288 five-minute points: approximately 13,824 forecast points per day,
414,720 over 30 days, and 5,045,760 over 365 days. Completed scoring can add the same
number of `forecast_point_scores` rows. Runs, operation attempts, and reserve runs
each grow by about 48 rows per day (1,440 over 30 days; 17,520 over 365 days), while
opportunity-evaluation growth depends on the number of candidates evaluated.

Indexes cover forecast run type/creation time, points by run/period, scores by score
time, attempts by start and status/boundary, reserve runs by evaluation/forecast,
and opportunities by reserve run. They support bounded reads but do not bound disk
growth. Until a separately reviewed retention policy prunes forecasts and their
cascading scores/reserve audit consistently, operators should monitor PostgreSQL
table/index size and scoring backlog. This is a documented operational risk and a
post-release retention follow-up; v0.5.0 does not silently delete audit history.
