# Home Energy Optimiser

Phase 1 is a strictly read-only collector for Home Assistant, Amber Electric,
Solcast, and GoodWe telemetry. It stores five-minute observations in local SQLite,
checks data quality, and builds a simple historical household load profile. It
cannot issue a Home Assistant service call or hardware command.

Requires Python 3.12 or newer.

## 1. Create local configuration

Create `.env` in the repository root (it is ignored by Git):

```dotenv
HA_URL=http://homeassistant.local:8123
HA_TOKEN=replace-with-a-long-lived-access-token
TIMEZONE=Australia/Brisbane
DATABASE_PATH=data/energy_history.db
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

The default database is `data/energy_history.db`. Repeating collection in the same
five-minute slot updates that slot rather than creating a duplicate. The first run
after upgrading automatically adds domain-health columns without deleting existing
observations.

## 5. Run the continuous collector

```powershell
python tools/run_collector.py
```

It collects on clock-aligned five-minute boundaries, reconnects after transient
read failures, and stops with Ctrl+C.

## 6. Inspect the database

```powershell
python tools/inspect_history.py
python tools/inspect_history.py --days 7 --limit 20
python tools/inspect_history.py --json
```

Inspection reports healthy/unhealthy counts separately for telemetry, price, solar,
and weather. Overall health follows telemetry during Phase 1. Missing price or solar
forecasts therefore remain visible but do not discard sound household-load samples.
The report also shows five-minute collection coverage, its longest missing run,
average domain scores, warning/error totals, and common structured issues.

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
and confidence. Its leading result is only a hypothesis; no sign convention is
selected or saved.

## 8. Export history to CSV

Dates use the configured local timezone and include the full start and end dates:

```powershell
python tools/export_history.py --start 2026-08-01 --end 2026-08-07 `
  --output data/exports/history-2026-08-01-to-07.csv
```

CSV export reads the selected SQLite rows and does not modify them.

## 9. Run validation

```powershell
pytest
ruff check .
black --check .
git diff --check
```

See [architecture](docs/architecture.md), [data model](docs/data_model.md), and
[security](docs/security.md) for design details and safety constraints.
