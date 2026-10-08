# Offline paired synthetic prototype v1

This uncommitted prototype implements an offline calculation, not an application
feature or a model of installed GoodWe equipment. Its identity is
`offline-paired-synthetic-v1`. No application version, policy, outcome-v2 field,
configuration, database or runtime entry point changes.

## Source and authority

The worktree starts at locally verified v0.6.5 commit
`a93532b9ad5d604ee69a8215bb8ee9b5482e7af4`; no fetch was used.
The original design and erratum remain unchanged, with independently checked
file-byte SHA-256 values:

| Original artifact | SHA-256 |
| --- | --- |
| offline-paired-economic-evaluation-design.txt | `68cc021a9bd55fed8f21a555687475bfbcf62b3dc3a35d9ef2630e2bbb5b041c` |
| acceptance-report-erratum.txt | `6e6c6d81fc446f51e2528626a605a3e94212c92e1d43f874b68c24bc58c14060` |

These match the source-aligned brief. The settled F3 rule is one second per
internal forecast boundary; five distinct one-second gaps total five seconds.
This simulator requires complete cash-input coverage and applies no gap tolerance.

| Source concept | Implementation |
| --- | --- |
| Design sections 2, 6, 7: distinct accounting and paired value | Pure ledger comparator; observed accounting and expected candidate value are explicitly not evaluated or rewritten |
| Section 3: passive reference and common continuation | PV first, passive battery charging/discharging, residual site flows; same state-dependent policy after expiry |
| Sections 4, 5: timing and one-action deviation | Explicit ready time, aligned branch point, frozen supplied schedule, original expiry, no catch-up |
| Sections 6–9: balance, domains and terminal treatment | Explicit AC/DC domains, efficiencies, port limits, curtailment, feasibility and terminal reserve checks |
| Sections 8–9: missing data, load/PV and intervention limits | Strict synthetic coverage admission; no historical/intervention reader |
| Sections 10–13: examples, provenance, tests and minimum scope | Native A–C witnesses separate from public 24-hour fixtures; four dispatch actions only |

The approved narrower brief fixes terminal equality at 1e-6 kWh and requires both
terminal reserves. The export example is a supplied ledger witness, not an export
dispatch implementation. The released source's energy-flow concepts and interval
tests informed the implementation; the prototype does not import its configuration,
persistence, replay or client modules. Existing production assumptions are not
fallbacks for synthetic inputs.

## Components and invocation

- `src/energy_optimizer/offline_paired_synthetic.py`: frozen typed inputs,
  strict admission, pure kernel, passive policy, action overlay and comparator.
- `src/energy_optimizer/offline_paired_fixtures.py`: allowlisted byte-pinned fixtures.
- `tools/evaluate_paired_synthetic.py`: fixed-fixture CLI, deterministic JSON stdout.
- `tests/test_offline_paired_synthetic.py`: independent rational arithmetic,
  constraint, admission, timing, invariance and side-effect tests.
- `tests/fixtures/offline_paired_synthetic/`: ten deliberately authored fixtures.

From this checkout, using the already installed Python environment:

```powershell
python tools/evaluate_paired_synthetic.py --list
python tools/evaluate_paired_synthetic.py --fixture day_charge_A_extension
```

The CLI prepends this checkout's `src` and accepts only seven named, hash-pinned
24-hour fixtures. It accepts no arbitrary file, real-record input or output path.
Native short witnesses are not CLI evaluations. A synthetic label alone does not
admit a private dataset. JSON retains source, fixture, implementation, assumptions,
schedule and complete semantic input hashes. Invalid admission returns explicit
reasons and unavailable values; an admitted but economically ineligible case
retains diagnostic results. No .env, network, database or application startup is
needed. No optional numerical, network or database dependency is imported.

## Approved synthetic semantics

Only HOLD, PRESERVE_BATTERY, CHARGE_BATTERY_FROM_GRID and
DISCHARGE_FOR_SELF_CONSUMPTION are dispatchable. HOLD is modelled passive
self-consumption, not certified firmware behavior. Preserve inhibits discharge;
grid charging also inhibits discharge and uses remaining site/charge/headroom
budgets. Self-consumption discharges only into household deficit and never exports.
Reduced delivery is reported without retry or later energy compression.

Every case supplies capacity, physical minimum, frozen policy floor, terminal
reserve, separate charge/discharge efficiencies, site and battery port limits,
domains, topology, PV abstraction, curtailment permission and interval meaning.
The only supported topology is `synthetic_ac_bus_independent_ports`; a shared
hybrid-inverter envelope is rejected. Powers are nonnegative piecewise-constant
interval-average kW. Prices may be zero or negative. All coverages are complete,
strictly contiguous and nonoverlapping.

The branch point is the first five-minute boundary at or after readiness, including
an already aligned time. Initial energy must be supplied exactly there. Public
evaluation ends exactly 24 hours later. Schedule clipping preserves expiry and
loses nominal pre-branch request; it cannot move an opportunity forward. No
evaluation price selects or reschedules an action.

The paired kernel uses common action, energy-budget, load, PV and price boundaries,
then common battery saturation/floor events. These latter events follow the
declared constant powers; they do not invent within-interval input shapes. Both
arms retain identical partitions, including when only one saturates. There is a
4096 elementary-interval bound. Microsecond event timing and a 1e-9 arithmetic
epsilon are numerical implementation limits, not telemetry accuracy.

For each interval, all flow energies are AC kWh and E is stored/DC kWh:

```text
used_PV = available_PV - curtailed_PV
used_PV + import + discharge = served_load + export + charge
E_next = E + eta_charge*charge - discharge/eta_discharge
loss = (1-eta_charge)*charge + (1/eta_discharge-1)*discharge
cash = export_price*export - import_price*import
```

Limits restrict flows before updating state. Neither contradictory import/export
nor charge/discharge is permitted in an elementary interval. Unserved load makes
the path infeasible and the full-demand balance shortfall is retained. Available
PV and explicit spillage are synthetic; curtailed real output cannot establish
counterfactual available PV. Total load includes fixed EV consumption either
directly or as an explicitly added separate series, never both. Vehicle battery
power is not a household AC-load substitute.

Initial energy below policy floor but within physical bounds is preserved without
top-up/clamping or further deliberate discharge. Initial shortfall, signed minimum
margin and additional shortfall are distinct. The primary profile's terminal
reserve equals its frozen policy floor, represented separately from physical minimum.

Primary gross comparative value is action cash minus reference cash only when
inputs are admitted, both paths are feasible and serve load, terminal energy
matches within 1e-6 kWh, and both meet terminal reserve. Terminal residual remains
visible. Otherwise that field is null with exact reasons. This is a modelled
variable-energy gross difference, not realised savings or net economic advantage.
Explicit terminal-lambda and wear sensitivities remain separate and cannot restore
eligibility. Wear uses discharged DC kWh once. Missing wear is not modelled, not zero.
Existing opportunity-cost estimates are never added again. Overlapping comparisons
are non-additive and must not be summed as achievable savings.

## Native arithmetic witnesses and independent results

These retain original arithmetic durations. Their JSON adds explicit unused port,
capacity and input parameters needed by the prototype; those additions are recorded
as fixture assumptions, not claimed as original design data.

| Witness | Arithmetic | Diagnostic cash difference | Terminal difference | Primary |
| --- | --- | ---: | ---: | --- |
| A, two hours | 2 AC charge at .20; .9 charge and .9 discharge yield 1.8 stored then 1.62 AC serving .50 load | +.410 AUD | 0 kWh, both 10 | +.410 AUD |
| B, one hour supplied ledger | 2 DC discharged at .9 yields 1.8 AC exported at .60 | +1.080 AUD | -2 kWh | Unavailable: unmatched terminal energy |
| C, one hour | 1 household baseline + 1 fixed EV; preserve imports 2 at .50 while reference discharges 2 | -1.000 AUD | +2 kWh | Unavailable: unmatched terminal energy |

A losses are .38 kWh; explicit .08 AUD/discharged DC kWh gives .144 AUD
incremental wear and .266 AUD cash less wear. B's explicit .54 AUD/DC kWh
terminal lambda cancels its 1.08 cash gain before wear; .08 wear yields -.16.
At lambda .30, B's sensitivity is +.48 before wear, still no primary verdict.
C at lambda .50 balances -1 cash with +1 terminal value; falsely omitting EV would
halve its import bill. These are independent Fraction calculations in tests, not
values inferred from an operational candidate.

## Distinct fully specified 24-hour fixtures

A extension adds 22 hours with zero load/PV and declared .20/.10 prices. C extension
adds 23 hours with zero baseline/EV/PV and the same declared prices. These are new
synthetic assumptions; neither is a 24-hour reproduction of the original example.
Each JSON contains its own assumption note and complete input series.

| Public fixture | Expected diagnostic cash delta AUD | Terminal delta kWh | Primary / reason |
| --- | ---: | ---: | --- |
| day_charge_A_extension | .410 | 0 | .410 |
| day_preserve_C_extension | -1.000 | 2 | null; terminal unmatched |
| day_hold_identity | 0 | 0 | 0; both import 12 kWh, cost 2.40 |
| day_initial_policy_shortfall | 0 | 0 | null; both finish 2 kWh below required reserve |
| day_solar_curtailment | 0 | 0 | 0; each exports 1 kWh, spills 3 kWh, ends at 2 |
| day_charge_import_headroom | -.050 | .225 | null; terminal unmatched; only .25 of requested 2 AC kWh delivered |
| day_unserved_load | 0 | 0 | null; each has 1 kWh unserved demand |

An independent saturation regression uses E0=9, capacity 10, PV=1 kW, grid request
1 kW, eta=1, charge port=2 kW and prices .20/.10. Action reaches capacity in half
an hour, importing .5 and subsequently exporting .5; reference ends at the same
energy. Delta is -.05 AUD. Splitting otherwise constant prices at half an hour
must give the same result. Review found and corrected an initial whole-interval
headroom allocation bug using this failing independent test. No released code changed.

## Validation and future admission

Validation uses the existing interpreter with a sanitized environment, bytecode
disabled and pytest plugin autoload disabled. The prototype suite checks rational
arithmetic, independent flow reconciliation, source pins, four actions, interval
splitting, complete/gapped/overlapping/nonfinite inputs, terminal equality/reserve,
invalid topology, initial shortfall, curtailment, unserved load, signed prices,
schedule clipping/expiry, import/headroom/discharge constraints, CLI rejection and
an audited subprocess with network/.env access prohibited. Targeted existing pure
energy-flow and F3 boundary regressions are run separately. Exact final counts and
logs are recorded in the task's private validation manifest (79 prototype tests
and 18 existing regressions passed; 48 unrelated tests deselected). Ruff, Black,
four-file AST parsing and tracked diff whitespace checks passed. No service-dependent
full application suite or production validation is claimed.

Later real-record admission remains unimplemented and requires separate authority:
resolved immutable candidate schedules; decision-time availability and linked
forecast/reserve provenance; actual versus forecast classifications; validated
stored-energy mapping and sign conventions; measured/approved one-way efficiencies
and site/inverter constraints; AC household/EV reconciliation; comparable initial
state at readiness; complete time-weighted settlement/load/PV coverage; defensible
available-PV/curtailment treatment; intervention exclusion or explicit exogenous
handling; tariff and wear assumptions; cohort and overlap controls. Historical
availability, recommendation quality and realised savings remain unestablished.
