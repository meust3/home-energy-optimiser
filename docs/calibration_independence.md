# Calibration independence

v0.5.2 identifies a cohort by `forecast_type + model_version +
alignment_version + training_policy`. Metrics from another identity are never
allowed to satisfy current calibration readiness.

Two views are retained. Raw operational metrics weight every prediction row and
show how the rolling service performed. Independent evidence first groups rows by
identity, target five-minute slot, and horizon bucket, averages overlapping
predictions, and weights that target once. Evidence is then assessed by local
calendar date. The four buckets are 0–3, 3–6, 6–12, and 12–24 hours.

A date is substantially complete when at least 95% of its 288 target slots are
eligible in every required horizon. The default boundary is seven complete dates,
including at least five weekdays and one weekend, with all horizons represented.
Before that boundary, status is `insufficient_data` or `provisional` regardless of
raw overlap volume. These are project engineering heuristics, not universal
standards.

The report includes bias, MAE, RMSE, WAPE, signed energy error, and median/P90/P95
cumulative underforecast across independent dates. Daily cumulative energy error
averages the four horizon views, so the same realised energy is not counted four
times. Per-horizon metrics remain separate. WAPE is null when the actual-energy
denominator is zero. Positive signed energy error means actual demand exceeded the
forecast.

API fields explicitly separate raw prediction rows, eligible score rows, unique
physical actual/target slots, independent target/horizon cells, distinct local
dates, and calculated versus expected durable rollups.

`tradable_energy_is_calibrated` is true only when the exact forecast linked from
the reserve row matches the current identity, independent evidence is sufficient,
all horizons are present, status is good/acceptable, and no quality block exists.
This remains advisory; no command is issued.

The dashboard reads durable date/identity/horizon rollups. Requested and actual
ranges and any truncation are explicit; there is no silent newest-25,000-row
interpretation.
