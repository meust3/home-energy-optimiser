# Phase 1 data model

SQLite uses schema version 2 and one `observations` row per five-minute UTC slot.
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
  JSON, preserving `estimate`, `estimate10`, and `estimate90`;
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

Health issue summaries parse `health_domains_json` and report average stored score,
warning/error occurrence counts, and common issue code/entity/severity tuples per
domain. Legacy rows contribute to score averages but cannot contribute decomposed
issues because their original global issue list was not domain-specific.

CSV exports contain the observation columns in schema order. SQL `NULL` values are
empty CSV fields and JSON columns remain JSON text. Exporting never changes stored
rows.

Power-sign hypotheses are also derived, never stored. Each complete sample includes
PV power, house consumption, grid power, battery power, and optional battery-mode
context.
