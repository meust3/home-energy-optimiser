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
battery-positive discharge (21.75 W MAE, high confidence, 99.48% separation). The
installation-specific App example is:

```yaml
grid_power_sign: positive_export
battery_power_sign: positive_discharge
sign_convention_confidence: high
sign_convention_supporting_samples: 175
balance_tolerance_w: 250
```

This is evidence for manual configuration on this installation, not automatic or
universal configuration.

## Historical reprocessing

`tools/reprocess_observations.py` uses only manually configured, confirmed signs.
It defaults to dry-run and reports rows examined, repairable, unchanged, excluded,
baseline eligibility changes, residual statistics, and tolerance failures. Apply
requires both `--apply` and the explicit `--backup-verified` acknowledgement after
the production backup has passed a restore test.

Default repair targets only complete-raw rows whose normalized directions are
missing or unconfirmed. Already-confirmed rows are unchanged; exceptional
replacement requires the separately named `--override-confirmed` option. Repair
updates only derived flow, flow-health, baseline, provenance, and legacy-status
fields. It never updates raw PV/house/grid/battery values, BYD fields, EV charging
classification, event labels, EV session data, or manual annotation audit rows.
Manual annotation baseline decisions are also retained.

Each interpretation records its model, timestamp, conventions, supporting samples,
raw-input fingerprint, previous result, new result, and original legacy status.
Identical reruns do not duplicate audit entries. Rows outside residual tolerance
remain excluded.

Without direct EV telemetry, measured house load is preserved and the limitation is
recorded. If EV charging is known active but EV power is missing, the baseline stays
ineligible. Inferred EV power is never invented or subtracted.
