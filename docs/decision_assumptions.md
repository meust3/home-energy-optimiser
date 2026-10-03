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

Future corrected inputs carry `calculation_version=battery-shadow-evidence-v2`
and compact `action_window_demand_evidence`: consumed interval references, clipped
durations/energy, linked IDs, partial compatibility, coverage and failure windows.
Policy, assumption and outcome scoring versions remain unchanged. The unique
boundary-plus-policy key still prevents replacing an existing decision on retry.
No schema migration or historical repair accompanies these calculations.

Rows without this calculation marker retain legacy values and hashes. Historical
HOLD values are labelled clamped available energy on the dashboard, not signed
reserve margins; they are never recalculated. Diagnostic replay reports source
and replay calculation versions and whether the semantics match. A new replay of
a legacy row is a corrected diagnostic, not reproduction of its original output.

Snapshots must never contain Home Assistant/Supervisor tokens, database URLs or
credentials, full HA attributes, VINs, coordinates, SEMS credentials, or private
headers.
