# Shadow decision policy

`battery-shadow-policy-v1` is deterministic and does not claim mathematical or
global optimality. It rejects infeasible candidates, computes expected gross
variable-energy value, applies reserve/data/calibration gates, enforces the minimum
value, sorts by value, and uses a stable action precedence to break ties.

HOLD is the feasible zero-increment baseline whenever current state can be audited.
Grid charge is bounded by battery headroom, configured import limit, modelled charge
power, efficiency, complete import prices, and estimated future use. Preserve keeps
energy unchanged when reserve or forecast demand is material. Self-consumption is
bounded by forecast household deficit, discharge power, efficiency, and energy
above reserve. Export is bounded by both export and discharge limits and may not
cross the linked reserve. Defer export values the same bounded energy against a
later, higher export interval.

Every candidate retains separate `blocking_constraints` and
`warning_constraints`, its action window, battery/grid energy, reserve-before and
projected reserve margin, price coverage and averages, confidence, rank, ranking
components, and tie-break reason. Infeasible economic values remain null.

Non-HOLD selection additionally requires the exact linked identity—forecast type,
model version, `full_5m_v1` alignment, and training policy—complete current-identity
rollup backfill, independent date and weekday/weekend thresholds, every required
horizon bucket, and no truncated or blocking quality evidence.
