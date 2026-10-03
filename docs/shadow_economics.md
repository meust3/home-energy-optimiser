# Shadow economics

The only monetary label used is **expected gross variable-energy value**. It is not
profit, net profit, or a guaranteed bill saving. Fixed supply charges, uncertain
tax/tariff composition, battery degradation, demand charges, EV costs, unvalidated
physical loss behaviour, and operator/device response are excluded or disclosed.

For the current action window, Amber prices are integrated by their actual overlap
duration. Negative prices are retained. A one-second adjacent API boundary offset
is tolerated separately at each internal boundary, while larger gaps are exposed
and never interpolated. Leading/trailing gaps have no adjacency allowance.
Coverage snapshots distinguish represented seconds from tolerated offsets;
weighted prices use represented seconds only. Overlaps retain the existing sorted
start/end, first-covered-price rule; exact conflicting ties follow source order.
Conflicts are not independently resolved and can change value if source order
changes. This correction does not introduce a new conflict-resolution policy.

With energy in kWh and prices in AUD/kWh:

- grid charge value = future-use value of stored energy − current import cost;
- self-consumption value = avoided current import cost − future opportunity cost;
- export value = current export revenue − future opportunity cost;
- defer-export value = bounded comparable export energy × (later − current price);
- HOLD and preserve have zero incremental gross value.

Charge/discharge efficiency is explicit. `battery_delta` is battery-side energy;
`grid_delta` is grid-side energy. Export revenue can be negative. Each candidate
stores import cost, export revenue, avoided import value, opportunity cost, gross
incremental value, duration-weighted average import/export price, price horizon,
and coverage where applicable.

Reserve is never recalculated. Current battery energy comes from the persisted
observation (or SOC × configured usable capacity), and available energy is
`max(current battery energy − linked recommended reserve, 0)`. A projected margin
below zero makes discharge/export infeasible.
HOLD's signed margin is battery energy minus reserve; its available energy remains
clamped separately. A negative HOLD margin reports current shortfall without making
no-action HOLD impossible. Unknown margin means unknown reserve coverage.

Action demand partitions the recorded window: linked reserve household-demand
slots supply only the initial overlap before the operational full-five-minute
start, and operational points supply the remainder. Known shared household
hierarchy versions, baseline target, training policy, links and decision-time
reconciliation must agree. Stored reserve kWh represents an interval average and
is clipped in proportion to duration; operational W is integrated over overlap.
No intrainterval shape, EV addition or reserve-total addition is assumed. Gaps,
overlaps or incompatible evidence keep complete demand and deficit unavailable.

Solcast P10 may reduce the near-term household deficit conservatively; P50/P90 and
constraint classification remain context. No derating is applied and replenishment
is never guaranteed.
