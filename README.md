# Home Energy Optimiser

Phase 1 is a strictly read-only collector for Home Assistant, Amber Electric,
Solcast, and GoodWe telemetry. It stores five-minute observations in SQLite or PostgreSQL,
checks data quality, and builds a simple historical household load profile. It
cannot issue a Home Assistant service call or hardware command.

Requires Python 3.12 or newer.

## 1. Create local configuration

Create `.env` in the repository root (it is ignored by Git):

```dotenv
HA_URL=http://homeassistant.local:8123
HA_TOKEN=replace-with-a-long-lived-access-token
TIMEZONE=Australia/Brisbane
DATABASE_URL=sqlite:///data/energy_history.db
COLLECTION_INTERVAL_SECONDS=300
USABLE_BATTERY_CAPACITY_KWH=40
MAXIMUM_PLAUSIBLE_INVERTER_POWER_W=15000
LIVE_POWER_FRESHNESS_MINUTES=5
BATTERY_SOC_FRESHNESS_MINUTES=10
AMBER_CURRENT_PRICE_FRESHNESS_MINUTES=10
AMBER_FORECAST_FRESHNESS_MINUTES=60
SOLCAST_FORECAST_FRESHNESS_MINUTES=360
WEATHER_TEMPERATURE_ENTITY_ID=sensor.outdoor_temperature
WEATHER_CONDITION_ENTITY_ID=weather.home
WEATHER_FRESHNESS_MINUTES=60
GRID_POWER_SIGN=unknown
BATTERY_POWER_SIGN=unknown
SIGN_CONVENTION_CONFIDENCE=unconfirmed
SIGN_CONVENTION_SUPPORTING_SAMPLES=0
BALANCE_TOLERANCE_W=250
EV_CHARGING_ACTIVE_ENTITY_ID=
EV_CHARGING_POWER_ENTITY_ID=
EV_PLUGGED_IN_ENTITY_ID=
EV_ENERGY_REQUIRED_ENTITY_ID=
EV_READY_BY_ENTITY_ID=
EV_INFERENCE_ENABLED=false
EV_PLAUSIBLE_POWER_MIN_W=1800
EV_PLAUSIBLE_POWER_MAX_W=12000
EV_MINIMUM_SESSION_MINUTES=30
FORECAST_RETENTION_DAYS=365
MINIMUM_SOC_PERCENT=20
EMERGENCY_RESERVE_KWH=6
RESERVE_HISTORY_DAYS=28
RESERVE_RECENT_DAYS=7
RESERVE_MAX_HORIZON_HOURS=24
RESERVE_UNCERTAINTY_RATIO=0.20
RESERVE_FALLBACK_MODE=banded
RESERVE_FALLBACK_OVERNIGHT_KW=2.0
RESERVE_FALLBACK_MORNING_KW=2.5
RESERVE_FALLBACK_DAYTIME_KW=2.0
RESERVE_FALLBACK_EVENING_KW=3.0
RESERVE_FALLBACK_LATE_EVENING_KW=2.5
DEMAND_TIER2_MINIMUM_SAMPLES=3
DEMAND_TIER3_MINIMUM_SAMPLES=3
DEMAND_TIER4_MINIMUM_SAMPLES=6
DEMAND_TIER4_LOOKBACK_DAYS=7
DEMAND_COMPLETE_PERIOD_FRACTION=0.90
DEMAND_LOW_CEILING_COMPLETE_DAYS=2
DEMAND_MEDIUM_LOW_CEILING_COMPLETE_DAYS=7
DEMAND_WEAK_TIER_SHARE_CEILING=0.50
DEMAND_WEEKEND_DAYS=5,6
CHEAP_IMPORT_PRICE_PER_KWH=0.15
SOLAR_SURPLUS_THRESHOLD_KWH=1.0
CONSERVATIVE_FALLBACK_HOUSEHOLD_LOAD_KW=2.0
LOAD_PROFILE_MINIMUM_SAMPLES=3
```

Only `HA_URL` and `HA_TOKEN` are required. The weather entity IDs are optional;
omit them when weather collection is not configured. Weather health never changes
overall observation health during this phase. Never commit or paste the token into
logs, test data, or issue reports.

## 2. Install the editable project

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## 3. Test the Home Assistant connection

The safest connection test is a single no-save collection. It performs one
`GET /api/states` request and makes no state changes:

```powershell
python tools/collect_observation.py --no-save
```

## 4. Collect one observation

```powershell
python tools/collect_observation.py
python tools/collect_observation.py --json
```

`DATABASE_URL` selects one backend for the entire process: collector, inspection,
reserve estimation, forecasts, EV annotation, reprocessing, and exports. When it is
absent, the backward-compatible default is `sqlite:///data/energy_history.db`.
Repeating collection in the same
five-minute slot updates that slot rather than creating a duplicate. The first run
after upgrading automatically adds domain-health columns without deleting existing
observations.

Solcast energy summaries are normalized to kWh before they enter an observation.
In particular, next-hour and this-hour values reported by Home Assistant in Wh are
divided by 1,000; remaining-today, today, and tomorrow kWh values are retained. The
stored JSON also records the original numeric values, source unit, and conversion
status. If Home Assistant omits the unit, the normalized value remains missing
rather than being guessed.

Schema version 4 adds unit-explicit `solcast_*_kwh_json` columns without deleting or
rewriting older rows. The older ambiguous Solcast columns are retained only for
audit compatibility and may contain the pre-version-4 mixed-unit representation.

## 5. Run the continuous collector

```powershell
python tools/run_collector.py
```

It collects on clock-aligned five-minute boundaries, reconnects after transient
read failures, and stops with Ctrl+C.

## 6. Inspect the database

Verify connectivity, migration revision, counts, and integrity:

```powershell
python tools/check_database.py
python tools/check_database.py --json
```

```powershell
python tools/inspect_history.py
python tools/inspect_history.py --days 7 --limit 20
python tools/inspect_history.py --days 7 --details
python tools/inspect_history.py --json
```

Inspection reports healthy/unhealthy counts separately for telemetry, price, solar,
and weather. Overall health follows telemetry during Phase 1. Missing price or solar
forecasts therefore remain visible but do not discard sound household-load samples.
The compact default report shows five-minute coverage, first/last/longest missing
periods, domain health counts, average scores, warning/error totals, top issues, and
recent observations. Use `--details` for full issue, missing-value, and load-average
tables.

Home Assistant may leave `last_updated` unchanged while a value remains stable.
Freshness warnings consequently apply only to periodically updating powers, SOC,
prices, and required forecasts—not modes or price-spike context.

## 7. Validate power-sign hypotheses

Analyze raw GoodWe measurements without changing the database:

```powershell
python tools/validate_power_signs.py
python tools/validate_power_signs.py --start 2026-08-01 --end 2026-08-07
python tools/validate_power_signs.py --json
```

The tool compares PV, household, grid, and battery power against every grid/battery
sign combination. It reports sample counts, residual errors, battery-mode evidence,
median residuals, per-convention confidence, and supporting/contradicting examples.
Its leading result is only a hypothesis; no sign convention is selected or saved.
With high-confidence evidence it prints a suggested `.env` fragment for manual
review, but never edits configuration. The supplied 175-sample evidence supports
`positive_export` for grid and `positive_discharge` for battery; defaults remain
`unknown`.

Inspect configured conventions, raw/derived flows, residuals, EV context, baseline
eligibility, and event labels:

```powershell
python tools/inspect_energy_flows.py --days 7 --limit 20
python tools/inspect_energy_flows.py --days 7 --json
```

## 8. Export history to CSV

Dates use the configured local timezone and include the full start and end dates:

```powershell
python tools/export_history.py --from 2026-08-01 --to 2026-08-07 `
  --output data/exports/history-2026-08-01-to-07.csv
python tools/export_history.py --days 7 --output data/exports/recent-week.csv
```

`--from` and `--to` are inclusive and may be used independently. `--days` selects a
recent UTC window and cannot be combined with explicit bounds. Omitting all three
range options exports all observations. CSV export never modifies stored history.

## 9. Store and compare forecasts

Store a typed JSON run, attach available actual observations, and export the series:

```powershell
python tools/store_forecast_run.py forecast-run.json
python tools/compare_forecast_run.py 1
python tools/export_forecast_comparison.py --forecast-type solar_power `
  --from 2026-08-01 --to 2026-08-07 --format csv `
  --output data/exports/solar-comparison.csv
```

These tools write only forecast data and comparisons to the configured database/files. They do
not make recommendations or control devices.

## 10. Estimate a battery reserve

Estimate how much stored battery energy should be held for household and known EV
demand before the next plausible solar or cheap-grid replenishment window:

```powershell
python tools/estimate_reserve.py
python tools/estimate_reserve.py --json
python tools/estimate_reserve.py --source history
python tools/estimate_reserve.py --source history `
  --as-of 2026-08-02T12:00:00+10:00 --json
python tools/estimate_reserve.py --score-run 123
```

Interactive use defaults to `--source live`: one allowlisted `GET /api/states`
collection supplies current SOC and power, while demand comes from history in the
same configured database. The live observation is not saved unless `--save-observation` is supplied.
`--source history` uses the latest stored observation, reports its timestamp and
age, and warns when it is older than ten minutes. `--as-of` provides deterministic
history replay and must include a timezone offset.

The estimator does not recommend an executable action. Its output is marked
`ready_for_manual_review`, never `ready_for_execution`. Potentially tradable energy
is an analytical upper bound, not an instruction to export or discharge.

The default demand fallback uses configured local-time bands. Every default is at
least as conservative as the former 2.0 kW flat fallback. Set
`RESERVE_FALLBACK_MODE=flat` to retain the original single
`CONSERVATIVE_FALLBACK_HOUSEHOLD_LOAD_KW` assumption. Terminal and JSON output show
eligibility exclusions, weekday/slot sample qualification, and fallback energy by
band; these are configured assumptions and are never inferred from sparse history.

Before fallback, the forecast tries exact weekday/five-minute, weekday-or-weekend
30-minute, all-days 30-minute, and recent same-band tiers. Output reports every
slot's tier, samples, energy, variability, and fallback share. Broader tiers are
context estimates, not exact learned household patterns. The report separates data
availability, household-demand, opportunity, and overall confidence; entity
availability cannot override incomplete demand history. It also shows complete days
and overnights, tier shares, EV contamination risk, gross reserve, the battery cap,
unmet requirement, and current shortfall.

Each invocation stores the advisory five-minute demand projection in local SQLite
for later validation, even when a live observation itself is not saved. Use the
printed forecast-run ID with `--score-run` after the horizon to compare eligible
actual household energy with the forecast and inspect error by tier. Training never
uses observations at or after creation time and excludes the current partial local
day, preventing future-data leakage in historical replay.

See [reserve estimation](docs/reserve_estimation.md) for its assumptions,
confidence model, and limitations.

## 11. Reprocess historical derivations

Preview recovery of derived fields from preserved raw observations:

```powershell
python tools/reprocess_observations.py
python tools/reprocess_observations.py --json
```

Before applying, stop collection briefly and create a timestamped backup:

```powershell
Copy-Item data/energy_history.db `
  data/energy_history-before-reprocess-20260802.db
python tools/reprocess_observations.py --apply
```

Dry-run is the default. Apply updates derived columns only and appends auditable
derivation history; raw telemetry is never changed. Identical reruns are idempotent.

## 12. Annotate historical EV sessions

Annotate a known historical EV session locally (dry-run first):

```powershell
python tools/annotate_ev_session.py --start 2026-08-01T22:00:00+10:00 `
  --end 2026-08-02T05:00:00+10:00 --session-id overnight-charge
python tools/annotate_ev_session.py --start 2026-08-01T22:00:00+10:00 `
  --end 2026-08-02T05:00:00+10:00 --session-id overnight-charge --apply
python tools/annotate_ev_session.py --remove-session overnight-charge
python tools/annotate_ev_session.py --remove-session overnight-charge --apply
```

The tool requires timezone offsets, preserves direct EV power and all raw inverter
telemetry, never estimates missing EV power, and writes only local derived fields
plus reversible audit records. Reserve diagnostics report excluded known sessions,
retained direct-power rows, and remaining unidentified-contamination risk.

## 13. Run validation

```powershell
pytest
ruff check .
black --check .
git diff --check
```

See [architecture](docs/architecture.md), [data model](docs/data_model.md), and
[security](docs/security.md) for design details and safety constraints. Additional
notes cover [energy-flow conventions](docs/energy_flow_conventions.md),
[EV handling](docs/ev_handling.md), [forecast storage](docs/forecast_storage.md), and
the future [Home Assistant add-on plan](docs/home_assistant_addon_plan.md).
