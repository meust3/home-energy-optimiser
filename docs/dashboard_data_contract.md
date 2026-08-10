# Dashboard data contract

Pydantic response models define the v0.3.0 API. Timestamps are timezone-aware UTC
ISO 8601 values with `+00:00`; the browser displays them in Australia/Brisbane.
Unavailable data is JSON `null`, never zero. Non-finite numbers are converted to
null before validation, and Pydantic rejects NaN/Infinity.

## Units and directions

- Power fields end in `_w`; charts convert them to labelled kW for presentation.
- Energy fields end in `_kwh`.
- SOC and health scores end in `_percent`.
- Amber fields end in `_aud_per_kwh` and are labelled AUD/kWh.
- Durations and ages use `_seconds` or explicit minute fields.

Persisted normalized fields are authoritative: grid positive means export and grid
negative means import; battery positive means discharge and battery negative means
charge. The dashboard does not reimplement sign conversion. It displays
`grid_import_power_w`, `grid_export_power_w`, `battery_charge_power_w`, and
`battery_discharge_power_w` exactly as stored. Baseline load is also used exactly as
persisted. Unhealthy observations are retained and marked, not silently discarded.

## Available data

The latest observation supports raw telemetry, normalized flows, battery energy,
Amber prices, modes, balance residual, sign confidence, event labels, domain health,
baseline eligibility, and optional genuine charger EV power. Historical queries use
the same columns over a bounded range.

Forecast tables support run creation/horizon/model metadata, expected points,
optional stored lower/upper bounds, point metadata, and request-time actual/error
comparison. A missing uncertainty band stays null. A missing run returns the exact
empty-state message: “No persisted forecast series is available for this period.”

## Reserve subset

The current schema does not store a complete reserve result. A persisted
`reserve_estimator` forecast run supports:

- calculation timestamp and forecast horizon;
- current-state source;
- projected household demand points and their tier metadata;
- gross reserve requirement;
- capacity-capped reserve;
- household-demand confidence metadata;
- overall reserve confidence metadata.

Battery SOC/energy at calculation, EV demand, technical/emergency reserve split,
unmet requirement, shortfall, potentially tradable energy, opportunity state,
effective boundary reasoning, sufficiency, readiness, and complete explanation are
not persisted. Their typed fields remain null. The dashboard does not run the
estimator or add a migration to derive them.

## EV limitation

EV power is returned only when a stored observation has `ev_source="charger"` and a
real `ev_power_w`. Helper or inferred state is not displayed as measured EV power.
Until independent production telemetry exists, `ev_contamination_warning=true`
because household and baseline history may contain charging demand.

## Read-only guarantee

Dashboard repository methods select bounded rows and aggregates only. The forecast
comparison endpoint does not update `actual_value` or `error_value`; reserve and
forecast endpoints never create a run. There is no computation, scheduler,
configuration, action, or control endpoint in v0.3.0.
