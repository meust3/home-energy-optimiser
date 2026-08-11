# Forecast-series storage

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
import/export, and buy/sell prices. Retention is configurable, but automatic deletion
is intentionally absent from this milestone.
