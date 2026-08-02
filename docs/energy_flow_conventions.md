# Energy-flow conventions

The database preserves `pv_power_w`, `house_consumption_w`, `grid_power_w`, and
`battery_power_w` exactly as Home Assistant reports them. Directional fields are a
separate derivation and never replace raw values.

Supported grid configurations are `positive_import`, `positive_export`, and
`unknown`. Supported battery configurations are `positive_charge`,
`positive_discharge`, and `unknown`. If either is unknown, directional fields and
residual remain NULL and status is `unconfirmed`.

When confirmed, the balance residual is `PV + grid import + battery discharge -
house - grid export - battery charge`. Allocation fields use a transparent
deterministic accounting order and are derived estimates, not separately metered
facts. Excess residual makes flow readiness unhealthy without affecting telemetry.

The supplied 175-sample analysis strongly supports grid-positive export and
battery-positive discharge (21.75 W MAE, high confidence, 99.48% separation). This
is evidence for manual configuration, not automatic configuration.

## Historical reprocessing

`tools/reprocess_observations.py` uses only manually configured, confirmed signs.
It defaults to dry-run and reports eligibility, exclusions, residual statistics, and
tolerance failures. `--apply` recomputes derived flows, allocations, events,
baseline eligibility, and flow health while preserving every raw value.

Each interpretation records its model, timestamp, conventions, supporting samples,
raw-input fingerprint, previous result, new result, and original legacy status.
Identical reruns do not duplicate audit entries. Rows outside residual tolerance
remain excluded.

Without direct EV telemetry, measured house load is preserved and the limitation is
recorded. If EV charging is known active but EV power is missing, the baseline stays
ineligible. Inferred EV power is never invented or subtracted.
