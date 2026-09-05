# Shadow economics

The only monetary label used is **expected gross variable-energy value**. It is not
profit, net profit, or a guaranteed bill saving. Fixed supply charges, uncertain
tax/tariff composition, battery degradation, demand charges, EV costs, unvalidated
physical loss behaviour, and operator/device response are excluded or disclosed.

For the current action window, Amber prices are integrated by their actual overlap
duration. Negative prices are retained. A one-second adjacent API boundary offset
is tolerated for coverage, while larger gaps are exposed and never interpolated.

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

Solcast P10 may reduce the near-term household deficit conservatively; P50/P90 and
constraint classification remain context. No derating is applied and replenishment
is never guaranteed.
