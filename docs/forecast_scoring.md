# Forecast scoring

Scheduled baseline points are eligible for scoring only after their interval has
ended and the configured delay has elapsed. Scoring never modifies expected, lower,
upper, unit, horizon or point metadata.

For each completed point the scorer records separately:

- actual value when an observation value exists;
- whether an actual was available;
- whether at least one actual met existing telemetry-health and baseline-training
  eligibility rules;
- signed error (`eligible actual - expected`), absolute error and squared error;
- a missing reason (`no_observation`, `actual_value_missing`, or
  `actual_unhealthy_or_ineligible`);
- scoring timestamp and eligible sample count.

Missing and unhealthy actuals are never treated as zero and do not contribute to
MAE, bias or RMSE. Coverage is eligible scored samples divided by selected forecast
points. The bounded read-only API reports aggregate metrics and groups them by
forecast run selection, forecast type, horizon bucket, Brisbane local hour,
weekday/weekend and model version. Sparse groups truthfully return null metrics and
zero coverage.

The existing legacy comparison CLI remains available for historic stored forecast
types, but scheduled operations use only the separate score table. This separation
is the immutability boundary for v0.5.0.
