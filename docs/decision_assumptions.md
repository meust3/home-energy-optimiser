# Decision assumptions

Every run uses `battery-shadow-assumptions-v1` and stores compact, unit-explicit
items with `name`, `value`, `unit`, `source`, and `classification`. Allowed
classifications are observed, configured, modelled, policy, and unknown.

The initial set records usable capacity, charge/discharge efficiency, grid-charge,
export and discharge limits, import limit, linked policy reserve, linked emergency
reserve, and the minimum gross-value threshold. Values come from App/model config
or the immutable reserve row; they are not universal hardware facts. A zero App
limit means unknown and makes the dependent candidate infeasible rather than
silently assuming inverter capability.

The compact input snapshot also records observation/forecast/reserve identity,
calibration gate, demand/deficit, Amber coverage and averages, Solcast P10/P50/P90,
and the bounded analysis horizon. A canonical SHA-256 input hash covers policy,
boundary, inputs, constraints, and assumptions. The 288 forecast points remain in
their immutable forecast run and are referenced, not duplicated.

Snapshots must never contain Home Assistant/Supervisor tokens, database URLs or
credentials, full HA attributes, VINs, coordinates, SEMS credentials, or private
headers.
