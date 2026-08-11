# Dashboard data contract

Pydantic response models define the versioned API. Timestamps are timezone-aware UTC
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

If every directional value in a requested range is null and each collected row has
`sign_convention_status="unconfirmed"`, the API marks the normalized-flow gap as
caused by unconfigured signs. With no collected rows, it does not set that marker,
so the frontend retains the generic missing-history message. The configured signs
shown on Data Quality come from validated App runtime settings; persisted raw and
normalized values remain authoritative for the charts.

## Available data

The latest observation supports raw telemetry, normalized flows, battery energy,
Amber prices, modes, balance residual, sign confidence, event labels, domain health,
baseline eligibility, optional genuine charger EV power, and v0.4.0 nullable
vehicle SOC/status/freshness context. Historical queries use the same columns over
a bounded range.

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
not persisted. Their typed fields remain null. Latest vehicle SOC may be displayed
as current context only; it is not a reserve-run input or persisted result. The
dashboard does not run the estimator or derive missing values.

## EV limitation

EV power is returned only when a stored observation has `ev_source="charger"` and a
real `ev_power_w`. Helper or inferred state is not displayed as measured EV power.
Vehicle-cloud battery power is returned only as
`ev_vehicle_battery_power_w_raw`; it is never charger AC power. Vehicle location is
only `ev_at_home=true|false|null`. VIN, coordinates, full attributes, and exact
location are absent. `ev_contamination_warning` remains true without independently
measured charger AC power because complete energy separation is not available,
even when fresh confirmed charging rows are excluded from baseline training.

## Read-only guarantee

Dashboard repository methods select bounded rows and aggregates only. The forecast
comparison endpoint does not update `actual_value` or `error_value`; reserve and
forecast endpoints never create a run. There is no computation, scheduler,
configuration, action, or control endpoint in v0.3.0.
