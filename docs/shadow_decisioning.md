# Battery shadow decisioning

Version 0.6.0 is a battery-only learning release. The shadow engine
produces database evidence and a recommendation; it is not an executor. It has no
Home Assistant client, Modbus client, charger client, device address, service-call
method, or command queue. Every stored run must satisfy the database constraint
`no_command_issued = true`.

## Process and lifecycle

The existing Forecast Operations coordinator remains the only scheduling domain:

```text
five-minute collector -> forecast -> reserve -> shadow decision -> no execution
                                                   |
                                                   +-> delayed outcome scoring
```

There is still one App container, one Python process, one collector, one forecast
coordinator thread, and one dashboard server thread. A decision is attempted only
after the same coordinator has persisted both `forecast_run_id` and
`reserve_run_id`. Its logical key is the aligned decision boundary plus
`battery-shadow-policy-v1`, so restart/retry cannot create a duplicate.

The action window begins when evaluation actually starts and ends at the current
boundary plus the configured interval (30 minutes by default). This represents the
remaining portion of the current decision interval. Analysis beyond it is bounded
by the earliest demand, Amber import, Amber export, supported Solcast, or configured
analysis horizon. Missing action-window price coverage forces HOLD.

## Gates and states

`shadow_decisioning_enabled` defaults to false and creates no runs. When enabled,
`shadow_allow_non_hold_recommendations` still defaults to false: all candidates are
stored, but HOLD is selected with `non_hold_selection_disabled`.

A missing, stale, or unhealthy current observation/SOC blocks the run and selects
no recommendation. Missing or incomplete prices, insufficient exact-identity
calibration, incomplete rollup backfill, missing solar context, unknown limits,
or value below the threshold fail closed to HOLD. HOLD is a normal advisory result,
not a failure. Unknown values remain null.

The battery candidate family is HOLD, grid charge, preserve, self-consumption
discharge, export, and defer export. EV actions appear only as blocked capability
records because direct charger AC power, required energy, target SOC, and ready-by
evidence are unavailable.

See [policy](shadow_decision_policy.md), [economics](shadow_economics.md),
[assumptions](decision_assumptions.md), and
[outcome scoring](decision_outcome_scoring.md). An executor remains a separate,
future component requiring explicit controlled hardware validation and approval.
