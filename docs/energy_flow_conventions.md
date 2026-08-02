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
