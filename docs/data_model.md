# Read-only operational data model

SQLite uses schema version 5 and one `observations` row per five-minute UTC slot.
`slot_utc` is the primary key. A repeat collection for a slot uses a last-write-wins
upsert so a newer snapshot atomically replaces an earlier snapshot without creating
a duplicate.

The table stores:

- UTC slot, exact UTC collection time, and local collection time;
- battery SOC, estimated energy, raw battery power, and mode;
- raw PV, house, and grid power, plus inverter work mode;
- current Amber import/export prices and price-spike state;
- complete Amber interval lists as JSON;
- Solcast remaining-today, tomorrow, next-hour, this-hour, and today summaries as
  explicitly named `*_kwh_json` values. Each summary normalizes `estimate`,
  `estimate10`, and `estimate90` to kWh while retaining the numeric source values,
  source unit, and conversion status for audit;
- optional Solcast power-now, temperature, and weather condition;
- backward-compatible overall health flag, score, and issue JSON;
- telemetry, price, solar, and weather health flags and scores;
- the complete typed domain-health result as JSON.

Missing numeric values are SQL `NULL`. Missing forecast summaries are `NULL`; known
empty interval lists are JSON `[]`. Datetimes use ISO 8601 with UTC offsets. Boolean
values use SQLite integers 0/1. JSON is produced by the standard library and SQL
values are always parameterized.

## Domain health and scoring

Each domain starts at 100. Each error deducts 20 points and each warning deducts 5,
clamped to 0. Any error makes that domain unhealthy; warnings alone reduce its score.

- Telemetry requires SOC, battery power, PV power, house consumption, grid power,
  and valid timezone-aware Home Assistant timestamps. Mode and work-mode are
  informational.
- Price requires current import/export prices and both Amber forecasts. Price spike
  is optional context.
- Solar requires remaining-today, tomorrow, and next-hour summaries. This-hour,
  today, and power-now are secondary.
- Weather is optional and healthy by default in Phase 1.
- Overall health derives from telemetry health. It is not an average of domains.

## Version 1 migration

Migration is additive and transactional. Version 2 adds domain flags, scores, a
domain JSON column, and a telemetry-health index with `ALTER TABLE`; it does not
drop or rebuild observations. Because old rows do not contain enough information to
reconstruct domains, telemetry, price, and solar are backfilled from the legacy
global flag/score, weather is backfilled healthy at 100, and the JSON records
`legacy_global_health`. New collections store independently evaluated domains.

Load-profile queries use `telemetry_is_healthy`, including migrated rows according
to that best-effort mapping.

## Derived reports and exports

Collection coverage is computed rather than stored. Expected slots form an
inclusive five-minute UTC sequence. Without a requested window, the sequence spans
the first through last selected observation; `--days` includes empty slots between
the aligned cutoff and current aligned slot. Coverage is collected distinct slots
divided by expected slots.
Contiguous missing slots are grouped into periods; reports expose the first, last,
and longest period with inclusive endpoints, slot count, and duration.

Health issue summaries parse `health_domains_json` and report average stored score,
warning/error occurrence counts, and common issue code/entity/severity tuples per
domain. Legacy rows contribute to score averages but cannot contribute decomposed
issues because their original global issue list was not domain-specific.

CSV exports contain the observation columns in schema order. SQL `NULL` values are
empty CSV fields and JSON columns remain JSON text. Exporting never changes stored
rows.

Power-sign hypotheses are also derived, never stored. Each complete sample includes
PV power, house consumption, grid power, battery power, and optional battery-mode
context. Every tested grid/battery multiplier pair reports mean absolute, median
signed, median absolute, and root-mean-square residuals; per-convention fit
confidence; and representative supporting and contradicting observations.

## Version 3 migration

Version 3 additively extends `observations` with directional flow fields, balance
residual, sign status/evidence, optional EV fields, baseline training fields, event
label JSON, and flow-health flag/score. Existing raw columns are unchanged. Legacy
rows receive `unconfirmed` sign status, NULL directional values, and an ineligible
baseline rather than reconstructed assumptions.

`forecast_runs` stores source/model/horizon metadata. `forecast_points` stores
period bounds, expected/lower/upper values, units, nullable actual/error values, and
metadata. Foreign-key and type/time indexes support comparison queries.

Load-profile samples select `baseline_house_consumption_w` only where telemetry is
healthy and `baseline_training_eligible=1`.

## Version 4 migration and Solcast units

Version 4 additively creates five unit-explicit Solcast JSON columns. New
observations store every Solcast energy estimate internally in kWh: Home Assistant
`Wh` summaries are divided by 1,000 and `kWh` summaries are unchanged. A missing or
unsupported `unit_of_measurement` leaves normalized values missing; the parser keeps
the source numbers and unit/conversion status and does not guess.

The five legacy ambiguous `solcast_*_json` columns remain untouched so migration
cannot reinterpret or destroy existing rows. They may contain mixed representations
from collectors predating schema version 4 and must not be treated as normalized
kWh. New writes use only the `solcast_*_kwh_json` columns; legacy rows have `NULL`
there unless recollected through the normal same-slot upsert policy.

## Reserve forecasts

Reserve estimates are calculated on demand. Their household-demand horizons are
persisted as immutable `forecast_runs` with source `reserve_estimator`; five-minute
`forecast_points` retain tier, sample count, variability, and expected watts. This
reuses the existing forecast tables, so no destructive migration or observation
column is required. Advisory results remain separate from measured observations.

After a horizon, scoring fills nullable actual/error values from telemetry-healthy,
baseline-training-eligible observations and reports integrated actual energy,
forecast error, percentage error where valid, bias, and tier-level error. JSON
output also distinguishes gross reserve, the capacity cap, unmet requirement, and
current shortfall, with four separate confidence components.
Operational context echoes relevant stored modes, directional-flow status, prices,
weather, and EV state for audit; it remains input context rather than an instruction.

## Version 5 derivation audit

Version 5 additively adds derivation model/version, reprocessed timestamp,
structured metadata, and original-legacy status. The append-only
`observation_derivations` table stores conventions, raw-input fingerprint, previous
interpretation, result, model version, timestamp, and legacy status. Its unique
slot/model/fingerprint policy makes identical reruns idempotent while retaining new
audit records for changed inputs or models.

Historical reprocessing updates only derived flow, event, baseline, and flow-health
columns. Raw telemetry is absent from the update statement. Missing raw values,
invalid residuals, inadequate original telemetry quality, and known EV activity
without EV power remain baseline-ineligible.
