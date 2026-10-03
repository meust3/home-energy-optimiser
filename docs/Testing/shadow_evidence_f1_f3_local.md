# F1–F3 local correction candidate

Base: released v0.6.4, `10d79a809ae26ba32c739a3c233f68ca4a817f61`,
verified against its local tag and the acceptance receipt at `a169678c`.
No fresh installed binary, runtime flags or production connection is verified here.
This worktree is separate from development and retained AI evaluation worktrees.

## Implementation plan

1. Replace the action demand assembly in `evaluate_shadow_decision` with a
   bounded window integrator. Operational intervals own the aligned span; only
   compatible linked reserve household slots may supply the prealignment span.
   Validate linked IDs, known model/target/alignment, matching training policy,
   evaluation/history as-of and complete nonoverlapping intervals. Clip interval
   average energy proportionally; never add the reserve total or fill later gaps.
   Store compact consumed-segment references and failure reasons in existing JSON.
2. Use signed battery-minus-reserve for HOLD, retain the separate clamped available
   energy, and report unknown reserve coverage as null. Ranking order and HOLD
   feasibility stay unchanged. Label historical HOLD values as legacy available
   energy on the dashboard; never recalculate stored history.
3. Apply price tolerance to each internal adjacent boundary only; retain strict
   endpoints and duration weighting over represented seconds. Reject nonfinite
   prices. Document deterministic existing sorted-first overlap handling.

An additive calculation version in the input JSON identifies future semantics.
Policy/assumption/scoring versions and boundary-plus-policy deduplication remain
unchanged. No schema migration or historical rewrite is planned.

Regression checks cover partial/aligned/clipped/late windows, unavailable and
incompatible evidence, gaps/overlaps and bounded JSON; signed/unknown margins,
HOLD feasibility and legacy display; per-boundary price gaps and finite prices.
Use isolated SQLite fixtures and sanitized test environments with production,
provider and PostgreSQL test URLs removed. No disposable PostgreSQL database has
been established for this task; parity will be reported as unverified.

## Result and reviewed scope

Implemented in `shadow_decisioning.py`: `_action_window_demand`,
`_partial_demand_compatibility`, `_demand_segments`, the evaluation snapshot/HOLD
margin, ranking evidence and `integrate_price_intervals`. Existing JSON persistence
and API passthrough need no changes. The coordinator already supplies the full
linked reserve audit. Dashboard changes label legacy HOLD energy and show future
signed margins. `shadow_replay.py` labels source versus replay calculation versions;
it continues to perform no writes.

Compatibility is explicitly limited to `reserve-estimator-v1` and the released
`household-demand-hierarchy-v1-cohort-v1` baseline target with `full_5m_v1`, the
same training policy and matching recorded evaluation/history context. Both use
the shared household hierarchy at the same as-of time; reserve EV demand is a
separate quantity and is not joined. Operational header/interval inconsistencies,
foreign point links and malformed/nonfinite/missing evidence fail closed.
Only interval-average energy is proportionally clipped. Consumed references are
limited to 290 segments, sufficient for the configured maximum 24-hour action
interval; pathological fragmentation is explicitly unavailable.

Manual diff review and AST comparison confirmed that configuration defaults,
physical limits, assumption generation, candidate economics, solar allocation,
future-price proxy, hash algorithm and `score_shadow_outcome` are unchanged.
Ranking sort/tie rules are unchanged; `reserve_gate_passed` is descriptive metadata,
not a filter. Forecast-card renderer, queries, eligibility thresholds and delays
are unchanged. No migration, policy rename or release version was introduced.

## Synthetic before/after calculations

These are independent local fixtures, not repaired production rows. The comparison
executes the exact Git-pinned v0.6.4 module and corrected local module with identical
inputs: action at boundary +20 seconds, end +30 minutes, 0.130174 kWh partial
reserve demand, then five operational intervals at 1000 W, battery 25.6 kWh,
reserve 40 kWh and next-hour Solcast P10 0.2 kWh.

| Quantity | Released v0.6.4 | Corrected future calculation |
|---|---:|---:|
| Complete action demand | Unavailable | 0.130174 + 25/60 = 0.546840667 kWh |
| Existing conservative deficit | Unavailable | 0.546840667 − 0.2 × 1780/3600 = 0.447951778 kWh |
| Available energy above reserve | 0 kWh | 0 kWh |
| HOLD signed reserve margin | 0 kWh (clamped) | 25.6 − 40 = −14.4 kWh |
| HOLD reserve coverage metadata | true | false |
| Selected action in forced-HOLD fixture | HOLD | HOLD |
| Separate 30-minute price fixture, isolated 2s internal gap | 100%, complete | 1798/1800 = 99.888889%, incomplete |
| Price fixture represented-duration weighted price | 0.099777531 AUD/kWh | 0.099777531 AUD/kWh |

One-second internal offsets remain protocol-complete individually. Endpoint gaps
have no such allowance, including subsecond gaps. Missing demand never becomes
zero; no incomplete partial sum is consumed as complete demand.

## Validation

- Full Python suite: **476 passed, 15 skipped** (63.87s), before the final narrow
  operational-header inconsistency guard and its regression case.
- Final focused Python rerun after that review correction: **111 passed, 1
  skipped** (5.23s), covering shadow decisions, outcomes, persistence, coordinator,
  replay and the 62 new F1–F3 cases.
- JavaScript: **6 passed, 0 failed**, including signed/legacy/unknown decision
  rendering and the existing forecast chart regressions.
- Ruff, Black check (112 files), JavaScript syntax and `git diff --check`: passed.

PostgreSQL integration tests were skipped because no owned disposable local
database was established. Existing installed dependencies were reused. The test
launcher strips inherited database selectors, HA/Supervisor/provider tokens,
secrets and API credentials before launching tests; `.env` was not opened. SQLite
fixtures use isolated temporary paths. No services were started and no provider,
production, hardware or dashboard-runtime connection was used.

## Historical treatment and limits

New snapshots carry `battery-shadow-evidence-v2` inside their existing input JSON.
Old snapshots/hashes/candidates/outcomes are not rewritten. Boundary-plus-policy
deduplication still refuses replacement, including a corrected retry over an older
row. The dashboard preserves old HOLD values with an explicit clamped-available-
energy label. Diagnostic replay labels any source/replay semantic difference.

The corrected evidence is not forecast accuracy, a validated battery trajectory or
economic savings. Outcome-v2 selected/HOLD simulation, comparison, hindsight,
regret and simulated reserve safety stay unavailable. Unknown power limits still
block dependent candidates; non-HOLD selection is not enabled by this batch.
Current installed source/flags and production behavior remain unverified in this
local task. PostgreSQL parity and browser visual QA remain unverified. Conflicting
price ties retain source-order dependence; a larger conflict-resolution policy is
outside this correction. Decision-ready time, calibration-source provenance,
future maximum-price valuation and complete-card performance remain outside scope.

## Future acceptance checklist — requires separate deployment authorization

1. Confirm reviewed build identity and new calculation marker. Preserve current
   HOLD-only, calibration, routing and retention settings; no migration is expected.
2. Read a bounded sample of newly created decisions with their linked records.
   Recompute normal partial/aligned/clipped action demand from consumed references,
   check complete durations once only and confirm precise reasons for unavailable
   evidence. Do not reprocess history or inject price fixtures into production.
3. For available below-reserve examples, verify signed HOLD margin, separately
   clamped available energy and false reserve coverage metadata. Unknown values
   remain null; blocked runs retain no selected action.
4. Verify represented price durations and individually tolerated boundaries from
   existing new evidence; larger and endpoint gaps remain incomplete. Confirm
   unchanged price weighting and no provider-array mutation.
5. Confirm one coordinator/collector, no-command invariants, HOLD-only selection,
   unchanged outcome-v2 null comparison fields, and no writes to prior records.
6. Confirm Forecast vs Actual retains baseline eligibility, matched intervals,
   missing/future actuals and existing threshold/delay behavior. Do not lower
   thresholds to obtain a complete card.

**Ready for local review.** Corrections may be reviewed alongside descriptive
HOLD-only shadow evaluation. They do not make comparative economic performance
available. The work stops unstaged and uncommitted; release and deployment are
separate decisions.
