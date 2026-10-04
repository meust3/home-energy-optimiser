# v0.6.6 data-quality candidate

This candidate is based on tagged v0.6.5 in `codex/data-quality-fixes`. The original
AI integration checkout is untouched. No production connection, migration,
historical repair, Home Assistant service call or hardware command was used during
implementation and validation. Publication and installation are not claimed here.

## Changes and contracts

The live Forecast vs Actual card preserves the newest forecast, reads bounded
elapsed observations when an official score is absent, and uses the same pure
eligibility evaluator as the scorer. Existing official scores take precedence.
Future intervals stay missing. The API reports actual source, exclusion reason,
official-score coverage, observed coverage, and unavailable uncertainty bounds.
Live summaries are ephemeral presentation queries; they do not persist scores,
run estimators or schedule calculations. Latest-complete selection still uses
official scores and the configured coverage threshold.

History and quality use one inclusive canonical observation window. Presets
contain exactly the named duration's number of five-minute slots (288 for 24h).
They end at the last UTC boundary at least 60 seconds before the request, allowing
collection to finish. The end is time-based even if collection stops. Custom
windows include slot starts at or after the requested start and at or before the
requested end. Charts use UTC-aligned aggregation buckets. History returns both
requested and effective boundaries and displays the effective range. Missing
slots are never interpolated. Telemetry incidents, collection gaps, unavailable
measurements and baseline exclusions have distinct reporting.

Energy-flow labels describe measured grid import/export and aggregate battery
charging/discharging. Charging is not attributed to the grid from its magnitude.
Displayed negative zero is normalized without altering measurements.

Solar diagnostics retain recorded PV energy and the first stored daily Solcast
snapshot. Day-in-progress and low-coverage days have no daily error or range
judgment. Complete sufficiently covered days report actual minus forecast, with
the percentage denominator explicitly actual energy. The additive signed-percent
field uses this convention; the legacy `p50_percentage_error` field retains its
forecast-minus-actual convention for existing consumers. Snapshot acquisition time is
shown; original forecast issue time remains unverified. These comparisons do not
prove curtailment, validate unconstrained generation or derate Solcast.

Scoring keeps its existing cutoff, chronological pending selection, 2500-point
limit, transaction, runtime guard and immutable forecasts/scores. Observation
reads are grouped by target UTC date and reused across overlapping predictions.
Each group permits at most a two-day span/576 observations, and fails rather than
silently truncating. Exact v1 and legacy half-open interval semantics are retained.
Successful cycles record scoring duration, batch size/limit and saturation in
existing metadata. An explicit bounded repository diagnostic reports pending
count (with truncation), oldest pending interval and its age; it does not run on
every dashboard poll.

## Local evidence

- Full suite using an owned disposable PostgreSQL 17 database: 516 passed in
  81.04 seconds on the final candidate. Candidate CI is a separate check.
- Node behavior: 9 passed; includes pending-score explanation, readable missing
  reasons, omitted empty-bound columns, negative-zero formatting, selection races
  and preserved v0.6.5 shadow evidence.
- SQLite/PostgreSQL regressions exercise observed-but-unscored actuals, missing
  slots, EV exclusion, immutable official-score precedence, legacy alignment,
  query batching and repeated-scoring idempotence.
- Ruff, Black, JavaScript syntax and whitespace checks pass.
- Browser QA uses explicitly synthetic local data, with no production access.
  It verifies observed pending actuals, readable missing-value explanations,
  incident recovery details and withheld partial-day solar errors. Dashboard asset
  versions are updated to invalidate cached scripts.

The retained 3 October snapshot checksum was independently verified as
`2dfe9345f116b97bc87184b8037dd1f61b9818053eecc82a43f3b1ccae915afb`
before restoring into a task-owned local PostgreSQL container. Two disposable
copies received the same missing-score workload. Both produced identical
fingerprints for 2500 score records, including eligibility, errors, missing
reasons and metadata. The baseline performed 2500 observation SELECTs/5001 total
statements in 6.23 seconds. The candidate performed one observation SELECT/three
total statements in 0.60 seconds. The restored snapshot contained 17343
observations and 715151 forecast points. This is a local measured improvement,
not proof that the later production query cancellation is resolved.

Private receipts and temporary fixtures remain in ignored `data/exports/`;
household records, database URLs and restored databases are excluded from Git.

## Uncertainty and model evidence

`tools/review_forecast_intervals.py` consumes an explicit local JSON export and
has no network/database interface. Its reusable evaluator checks current model,
alignment and training-policy identity; deduplicates physical target slots within
each lead-time group; excludes labels unavailable at the training cutoff; and
requires a local-midnight chronological split. P10/P90 residual candidates require
28 training dates, seven later dates and 100 samples in both parts of each
six-hour/local-time and horizon group. Nominal pointwise coverage is 80%, with a
predeclared five-percentage-point tolerance. A training-only band-median baseline
is reported on the same held-out points. A candidate pass never enables bounds.

The restored-snapshot review selected 55800 target/horizon records and used a
25 September local-midnight training cutoff. Twelve of 16 groups failed coverage;
four passed. Held-out coverage ranged from 57.69% to 88.41%. The candidate bounds
are therefore withheld from operational forecasting. EV-unverified history still
limits interpretation; neither pointwise interval coverage nor baseline MAE
establishes daily-energy accuracy or reserve safety. The point model is unchanged.

Charger AC power and temperature collection require identified, validated
read-only sources. Existing optional configuration paths remain available; no
entity was invented, hardware controlled, vehicle battery power substituted or
historical cohort relabelled to close those gaps.

## Release checks still required

Before publication/installation, verify the exact source/image and installed App
identity, confirm automatic App updates are disabled, take a fresh backup and
validate its isolated restore. Preserve HOLD-only and disabled retention settings.
This candidate requires no schema migration. Validate collection, dashboard,
forecast/reserve/scoring progress and unchanged historical records after the
controlled update; preserve the previous App image for rollback. Extended live
monitoring remains necessary before closing the scoring-timeout issue.
