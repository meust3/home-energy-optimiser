# Decision outcome scoring

## v0.6.1 correction: battery-shadow-outcome-v2

The v0.6.0 tag contains `battery-shadow-outcome-v1`. Its outcome estimates must
not be used to approve non-HOLD selection or establish decision quality. Version
v2 corrects observed accounting and explicitly withholds unsupported simulations.
Policy and assumption versions remain unchanged; schema head stays `20260905_01`.

The existing coordinator scores only after the stored action interval ends plus
`shadow_outcome_scoring_delay_minutes` (10 by default). One row is appended per
`decision_run_id + scoring_version`. New v2 rows never overwrite v1 outcomes,
original decisions, or candidates. Previously scored decisions can receive v2 rows
through the same bounded coordinator queue, using the available observation data.

Each observation approximates constant power and current price over its five-minute
slot. The scorer integrates only the overlap with the action window, including
partial first and last slots. The repository includes the overlapping first slot.
This is an estimate from samples, not a settlement-quality energy meter reading.

Observed gross variable-energy value is the sum, per slot, of export energy times
that slot's export price minus import energy times that slot's import price.
Negative prices are valid. It is not total energy multiplied by an average price.
Fixed charges, degradation and other omitted costs are not included.

Whole-window energy totals require complete slot coverage and finite, nonnegative
power for the corresponding flow. Observed value additionally requires both prices
and grid directions on every slot. Missing or invalid data leaves the affected
whole-window total NULL; measured zero remains zero. Slot, paired-price and paired-
grid-flow coverage are duration weighted and reported separately. Duplicate or
unaligned slots are rejected. No future observation is used.

## Counterfactual limits

The current code has no validated counterfactual battery trajectory. Observed
operation may contain manual intervention and is not a HOLD baseline. Adding a
candidate's nominal energy value to observed operation can double count existing
flows and does not establish the value of replacing those flows.

Therefore v2 leaves these fields NULL: simulated selected and HOLD values,
selected-versus-HOLD value, hindsight action/value, regret, simulated minimum
battery energy and simulated reserve breach. Counterfactual confidence is
`unavailable`. An observed battery minimum is not stored as a simulated minimum.
The original decision-time reserve feasibility checks and candidate values remain
available; they are not proof of realised reserve safety.

The dashboard shows corrected observed value for v2, marks v1 estimates as legacy
and unvalidated, and states that decision comparisons are unavailable. The API
retains immutable legacy rows and their scoring version for audit. Consumers must
not combine v1 and v2 into a decision-quality result.

A later independently reviewed model must define HOLD behaviour, apply each
candidate to the same exogenous load/PV evidence, reconcile energy and battery
state with efficiencies and constraints, and address terminal stored energy and
operator intervention before restoring these metrics under a new scoring version.
This correction does not implement that model or alter recommendation policy.

Intervention evidence remains probabilistic and cannot establish who acted or why.
Shadow operation never issues a device command.
