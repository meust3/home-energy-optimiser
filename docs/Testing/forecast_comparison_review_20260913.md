# Forecast comparison investigation - 2026-09-13

## Findings

A bounded, read-only operational query checked the 06:00 scheduled run for the
06:05-07:45 Australia/Brisbane interval shown in the screenshot. It did not run
application development code against production or change stored evidence.

- The chart incorrectly used actual-observation availability to gate every
  series, hiding future expected values despite all 288 forecast points existing.
- The Forecasts comparison endpoint averaged stored baseline observations without
  the telemetry-health and baseline-eligibility rules used by calibration.
- Eight observations from 07:10 through 07:45 were explicitly excluded from
  baseline training because charging was known but charger AC power was absent.
  They were nevertheless included in this view's MAE/bias and actual curve.
- For these 21 original slots, using the 13 comparable observations changes MAE
  from the displayed 1,972.571 W to 553.538 W, and bias from 1,710.762 W to
  +130.615 W (actual minus forecast). These are partial-run metrics, not evidence
  that the complete forecast is accurate.
- At 07:05 the expected value was 1,545 W and observed demand was 5,688 W. The
  stored charging flag was false and eligibility true. Its +4,143 W error remains
  included; no EV session is inferred retrospectively to improve the metrics.

## Correction

The read-only comparison query now applies baseline eligibility and telemetry
health, rejects materially negative household demand, preserves unfiltered
observations separately in the response, and explains unavailable comparisons.
No historical forecast, observation, score, policy or model value is rewritten.
Non-baseline forecast types retain their original actual-variable mapping.

Forecast and bound visibility is independent of actual availability. The graph
uses timestamp positions and the selected horizon, with dated axis ticks for
24-hour runs. Late responses cannot overwrite a newer selection, and periodic
run-list refresh preserves an older selection when it is still listed. Missing
and excluded actuals remain gaps; excluded counts are separate from absent data.

No model adjustment, schema migration, release publication, production update,
configuration change, or hardware command is part of this fix.

## Validation

- Full regression suite with disposable PostgreSQL 17 enabled: **377 passed**.
- Focused dashboard suite against SQLite and disposable PostgreSQL 17: 28 passed.
- Node behavioral tests: full expected series with partial/no actuals, changed
  dated axes on run selection, stale responses, and selected-run preservation.
- Browser visual check with explicitly synthetic local data: the full forecast
  spans the graph; switching 06:00 to 08:30 changes horizon and axis dates/times
  from 06:05-06:05 to 08:35-08:35.
- Ruff, Black and JavaScript syntax checks; no development production connection.

The fix is on `codex/fix-forecast-comparison`; production remains v0.6.1. A release
and controlled update are still needed to display these changes in Home Assistant.

Deployment follow-up: v0.6.2 was released and installed on 2026-09-13. See
[production acceptance](v062_production_acceptance_20260913.md). The earlier
release-pending statement describes the investigation checkpoint.
