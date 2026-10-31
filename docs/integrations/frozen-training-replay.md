# Immutable historical training replay

`python -m tools.replay_demand_population` runs the existing demand estimator
against an explicitly supplied original sample population. It has no configured
database, network, credential, backfill, live mode or output-overwrite path.
Existing collector, scheduled forecasts, operational training and reserve readers
are unchanged. Legacy database `as_of` readers still bound sample time only; do
not describe their current eligibility flags as knowledge-time reconstruction.

## Trusted input contract

Use a genuinely retained original study population whose SHA-256 is already bound
in the independently retained original study manifest. Supply that digest via
`--expected-sha256`. Do not calculate a new digest from today's database and
backdate its capture metadata. If the original population/manifest cannot be
established, historical eligibility is unavailable: stop that historical study.
The tool provides no database fallback, automatic audit reconstruction or repair.

Checksums establish exact bytes, not truthful dates or provenance. A caller can
fabricate/backdate JSON and its hash; this tool cannot authenticate its historical
origin. Therefore output always retains `provenance_verified=false` and must not
be represented as independently qualified historical evidence. Custody and the
external manifest must be reviewed separately before drawing historical claims.
This boundary protects against later database mutation and accidental population
substitution, not a dishonest operator or compromised original evidence store.

The reusable `freeze_training_population(rows, captured_at=..., source_id=...)`
function serializes already supplied rows for a new study's capture step. It does
not query a database or make a new snapshot into evidence for a past decision.
Retain its exact bytes and bind their hash in the original study manifest at
capture. Do not reconstruct old frozen selector populations through this helper.

## Format and execution

The JSON format is `immutable-training-population-v1`, with `captured_at_utc`,
`source_id` and full original `observations`. Each row must retain aware slot,
observation UTC/local timestamps, explicit health and eligibility flags and the
nullable baseline demand. Extra provenance and raw fields remain intact. Naive,
duplicate, missing-eligibility, nonfinite-demand and future-at-capture rows are
refused. Maximum population size is 16 MiB / 50,000 rows. Missing demand remains
missing; normal estimator eligibility rules continue to apply.

```powershell
python -m tools.replay_demand_population original-population.json --expected-sha256 <digest-from-original-study-manifest> --decision-at <aware-time> --start <aware-time> --end <aware-time> --minimum-samples 3 --fallback-kw 0.8 --output new-replay.json
```

Capture must be at or before the decision, and forecast start at or after it.
Output includes input identity, policy and no-command metadata plus the estimator
result. This is a new offline analytical result, not a persisted production run,
measured forecast accuracy or proof of economic benefit. Existing output files
and invalid inputs are refused with exit 2. No original artifact is modified.
