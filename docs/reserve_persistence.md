# Reserve persistence

After a successful scheduled forecast, and only when reserve snapshots are enabled,
the coordinator calls the existing reserve estimator at the same evaluation
timestamp with history bounded to that timestamp. The calculation and opportunity
algorithms are unchanged.

`reserve_runs` stores the complete typed advisory result: observation source/time
and age, battery SOC/energy/capacity, forecast horizon, household and EV demand,
technical/emergency/uncertainty components, gross and capped requirement, unmet
requirement, current shortfall, recommendation, nullable tradable energy, confidence
components, readiness, reasoning, health, operational context, demand forecast,
model version and associated scheduled forecast run. The first opportunity and
effective boundary are retained as portable JSON/JSONB. Every evaluated opportunity
has an ordered child row in `reserve_opportunity_evaluations`, including its full
analysis and expected replenishment details.

For a scheduled run created between boundaries, `operational_context_json` records
the linked forecast reconciliation. Reserve begins at evaluation time and its
existing partial slot covers evaluation to the linked `full_5m_v1` start. Exact
shared full intervals are identified without adding the linked forecast energy a
second time; any partial reserve end is recorded separately. The components
reconcile to persisted household demand, while the linked operational run remains
exactly 288 full five-minute points.

`potentially_tradable_kwh` remains SQL `NULL` when the estimator says it is
unavailable; it is never changed to zero. `command_issued` is always false and is
protected by a database check constraint. These rows are an audit trail, not an
instruction or approval to operate hardware.

The dashboard Reserve History endpoint is bounded to at most 1,000 rows and exposes
only non-secret analytical fields. It has no run-now or mutation route.

Alembic revision `20260812_01` creates the reserve and forecast-operation audit
tables additively. Its real downgrade removes only v0.5.0 audit/scoring data; it does
not rebuild or delete observations or legacy forecast values. Downgrade therefore
discards forecast-operation scores and reserve snapshots collected after v0.5.0.
Never substitute `alembic stamp` for the physical downgrade.
