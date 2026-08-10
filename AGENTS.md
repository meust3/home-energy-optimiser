# Home Energy Optimiser

## Project objective

Build a safe, explainable home energy optimisation platform using:

- Home Assistant
- GoodWe GW9.999K-EHA-G20 inverter
- approximately 40 kWh usable GoodWe battery storage
- Amber Electric wholesale import and export pricing
- Solcast solar forecasts
- historical household consumption patterns
- future EV charging support

The project should eventually optimise:

- battery grid charging
- battery discharge for household consumption
- battery export
- solar self-consumption
- battery reserve
- EV charging

The current phase is strictly read-only.

The canonical production database is PostgreSQL 17 on Synology. The production
migration and an end-to-end live observation write have been manually validated.
SQLite remains supported for local/offline development and as the retained final
pre-migration backup; it is not a production fallback.

Home Assistant App v0.2.0 was installed on the amd64 Home Assistant OS 18.1 NUC but
could not read Supervisor's root-owned `0600` options file. Version 0.2.1 is the
least-privilege startup patch candidate; it has not yet completed an operational
collection cycle on HAOS. Independent EV telemetry is not yet integrated, so EV
charging may reduce load-forecast and reserve estimate confidence.

## Architecture

The intended architecture contains four separate layers:

1. Collector
   - Reads Home Assistant entities.
   - Stores historical observations.

2. Forecaster
   - Forecasts household consumption.
   - Uses Solcast for solar generation.
   - May use weather for temperature-driven demand.

3. Optimiser
   - Produces an economic recommendation.
   - Explains the recommendation.
   - Does not control devices during the current phase.

4. Executor
   - Future component.
   - Must remain absent or disabled until controls have been manually tested.

## Mandatory safety boundary

The current project is read-only.

Allowed:

- HTTP GET requests to Home Assistant.
- Reading entity states and attributes.
- Writing observations to the configured PostgreSQL/SQLite repository or JSON files.
- Producing advisory recommendations.
- Running simulations and historical replay.

Not allowed:

- HTTP POST requests to Home Assistant.
- Calling Home Assistant service endpoints.
- Changing select entities.
- Changing number entities.
- Turning switches on or off.
- Issuing GoodWe battery commands.
- Issuing EV charger commands.
- Writing Modbus registers or coils.

Do not add command execution without explicit user approval.

## Home Assistant configuration

Connection details are supplied through environment variables:

- HA_URL
- HA_TOKEN

They may be loaded from a local `.env` file.

Never:

- print HA_TOKEN;
- log HA_TOKEN;
- store HA_TOKEN in SQLite;
- commit `.env`;
- include credentials in test fixtures.

## Home Assistant entities

### Amber Electric

Current import price:

- sensor.amber_home_assistant_general_price

Import forecast:

- sensor.amber_home_assistant_general_forecast
- forecast intervals are stored in the `forecasts` attribute

Current export price:

- sensor.amber_home_assistant_feed_in_price

Export forecast:

- sensor.amber_home_assistant_feed_in_forecast
- forecast intervals are stored in the `forecasts` attribute

Additional:

- binary_sensor.amber_home_assistant_price_spike

Ignore controlled-load pricing in the initial implementation.

### Solcast

- sensor.solcast_pv_forecast_forecast_remaining_today
- sensor.solcast_pv_forecast_forecast_tomorrow
- sensor.solcast_pv_forecast_forecast_next_hour
- sensor.solcast_pv_forecast_forecast_this_hour
- sensor.solcast_pv_forecast_forecast_today
- sensor.solcast_pv_forecast_power_now, if present

Preserve forecast uncertainty values where available:

- estimate
- estimate10
- estimate90

Solcast is the primary solar-generation forecast. Do not recreate its solar
forecast from generic weather data.

### GoodWe telemetry

- sensor.outside_back_goodwe_inverter_battery_state_of_charge
- sensor.outside_back_goodwe_inverter_battery_power
- sensor.outside_back_goodwe_inverter_battery_mode
- sensor.outside_back_goodwe_inverter_pv_power
- sensor.outside_back_goodwe_inverter_house_consumption
- sensor.outside_back_goodwe_inverter_meter_active_power_total
- sensor.outside_back_goodwe_inverter_work_mode

### Potential GoodWe controls

These are documented for future testing but must not currently be used:

- select.outside_back_goodwe_inverter_ems_mode
- number.outside_back_goodwe_inverter_ems_power_limit
- number.outside_back_goodwe_inverter_fast_charging_power
- number.outside_back_goodwe_inverter_fast_charging_soc
- switch.outside_back_goodwe_inverter_fast_charging_switch
- number.outside_back_goodwe_inverter_grid_export_limit
- switch.outside_back_goodwe_inverter_grid_export_limit_switch

The EMS mode options include:

- auto
- charge_pv
- discharge_pv
- import_ac
- export_ac
- conserve
- off_grid
- battery_standby
- buy_power
- sell_power
- charge_battery
- discharge_battery

Do not assume the precise behaviour of these names without controlled testing.

## Historical data

Record observations at five-minute resolution.

Each observation should include, where available:

- UTC timestamp
- local timestamp
- battery SOC
- battery power
- battery mode
- PV power
- household consumption
- grid power
- Amber import price
- Amber export price
- Solcast remaining generation today
- Solcast forecast tomorrow
- Solcast next-hour forecast
- current temperature when configured
- weather condition when configured
- data-health status

Store data through the shared persistence layer. PostgreSQL `home_energy` on the
Synology NAS is the canonical production source of truth. SQLite remains available
only for local/offline compatibility and tests:

- data/energy_history.db

`DATABASE_URL` is canonical and must be redacted in all output. Alembic is the
canonical deployed-schema migration framework.

Do not commit the database.

The Home Assistant OS production collector is packaged as a Home Assistant App
(formerly called an add-on). It authenticates to the Supervisor Core API proxy with
`SUPERVISOR_TOKEN`, requires an explicit external PostgreSQL configuration, and
must fail rather than fall back to SQLite. App packaging must not request host
networking, privileged mode, device access, the Docker socket, or Supervisor API
access.

Prevent duplicate five-minute observation timestamps.

Unhealthy observations may be stored, but missing values must remain missing.
Never invent or silently replace unavailable data.

## Household load forecasting

The optimiser must account for expected self-consumption before recommending
battery export.

Initial forecasting should be simple and explainable:

1. Average load by day of week and time interval.
2. Recent-history adjustment.
3. Conservative fallback when insufficient history exists.
4. Later, optional weather adjustment for heating and cooling demand.

Do not introduce machine learning before the basic profile has been validated.

Expected tradable battery energy should account for:

- battery energy available at current SOC;
- expected household demand until the next solar or cheap-price period;
- configured minimum SOC;
- backup reserve;
- forecast uncertainty;
- battery efficiency.

## Weather

Weather may be used to improve household-demand forecasting, especially:

- temperature;
- humidity;
- heating or cooling demand.

Weather must not replace Solcast for solar generation.

Weather integration is optional in the first collector version.

## Initial configurable assumptions

Keep these configurable:

- usable battery capacity: 40 kWh
- round-trip efficiency: 0.95
- minimum SOC: 20%
- initial grid-charge target SOC: 80%
- battery degradation cost: AUD 0.08 per discharged kWh
- minimum economic margin: AUD 0.10 per kWh
- maximum inverter power: 9,999 W
- conservative fallback household demand

These are initial modelling assumptions, not measured guarantees.

## Data health

Block advisory recommendations when required data is unhealthy.

Check for:

- unknown states;
- unavailable states;
- missing entities;
- invalid numeric values;
- stale timestamps;
- SOC outside 0–100%;
- implausible power readings;
- missing Amber forecasts;
- missing required Solcast values.

## Advisory actions

The initial optimiser may recommend:

- HOLD
- CHARGE_FROM_GRID
- PRESERVE_BATTERY
- USE_BATTERY_FOR_HOME
- EXPORT_BATTERY
- BLOCKED

It must not execute any recommendation.

Every decision must explain:

- current state;
- relevant forecasts;
- household reserve estimate;
- economic margin;
- assumptions used;
- data-health result;
- why alternatives were rejected;
- explicit confirmation that no command was issued.

Do not claim mathematical optimality for the first rule-based strategy.

## Coding standards

Use:

- Python type hints;
- Pydantic models or dataclasses where appropriate;
- pathlib for file paths;
- UTC timestamps internally;
- timezone-aware datetime objects;
- small, focused functions;
- explicit exceptions;
- structured logging;
- dependency injection for network and database components;
- unit tests for non-network logic.

Avoid:

- broad `except Exception` blocks unless errors are re-raised or clearly logged;
- hidden global state;
- duplicated entity IDs;
- embedded credentials;
- hardcoded local file paths;
- business logic inside command-line scripts.

CLI tools under `tools/` should call reusable code under `src/`.

## Repository structure

- src/energy_optimizer/: reusable application code
- tools/: command-line entry points
- tests/: automated tests
- data/: local SQLite database and exports
- logs/: local decision logs
- docs/: architecture and findings
- .env: local secrets, never committed

## Immediate milestone

Build only:

1. Read-only Home Assistant state ingestion.
2. Typed entity parsing.
3. Five-minute historical observation storage.
4. Data-health evaluation.
5. History inspection tools.
6. A basic explainable household load profile.

Do not build device control yet.
Do not build an executor yet.
Do not call Home Assistant services.

## Read-only operational data model

Raw GoodWe PV, household, grid, and battery power must always be preserved exactly
as reported. Directional energy flows may be derived only when grid and battery sign
conventions are explicitly configured. Unknown conventions must leave directional
fields missing and must not make raw telemetry unhealthy.

Optional EV telemetry and Home Assistant helper entities may be read with GET. They
must never be controlled or created by this project. Baseline household demand may
subtract direct EV power, but inferred EV power must never be silently subtracted.
Ambiguous inferred sessions are excluded from baseline training.

Forecast runs and projected-vs-actual points are stored in the database selected by
`DATABASE_URL`. Forecast
storage and comparison are analytical only and must not trigger device actions.
