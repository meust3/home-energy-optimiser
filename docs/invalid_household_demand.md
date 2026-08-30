# Invalid household demand

Raw GoodWe household demand is always preserved. Values below -1 W are considered
materially negative and receive telemetry issue and baseline exclusion reason
`invalid_negative_household_demand`. Zero, negative zero, and noise from -1 W to
zero remain valid and may be normalized to zero only after validation.

Invalid values have a null derived baseline and cannot train the load forecaster.
Forecast scores retain the raw actual where available but are health-ineligible,
have null error fields, and use
`invalid_actual_negative_household_demand`. Overlapping forecasts referencing the
same bad actual are excluded consistently, and rebuilt rollups omit them.

`python tools/reclassify_invalid_household_demand.py` is a read-only dry run. A
write requires both `--apply` and `--backup-verified`. It changes derived
eligibility/score fields, writes an idempotent derivation audit, invalidates
affected rollups for rebuilding, marks the historical observation's overall and
telemetry validity false, and never changes raw household power. The tool must not
be run against production as part of release development.
