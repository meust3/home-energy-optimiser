# Decision outcome scoring

Outcome scoring begins only when the stored action interval has fully elapsed plus
`shadow_outcome_scoring_delay_minutes` (10 by default). It appends one row per
`decision_run_id + scoring_version`; it never updates the original decision or
candidates. A later scoring algorithm therefore receives a new versioned row.

The scorer integrates only observations inside the original action window. It
records actual slot, price, and directional-energy coverage; import/export,
battery, household and PV energy; observed variable-energy value; simulated
selected and HOLD values; selected-versus-HOLD; the best feasible candidate from
the original family; regret; minimum observed battery energy; and possible reserve
breach.

Hindsight does not add a new action or relax an original feasibility constraint.
All counterfactuals are simulations, not physical measurements. Confidence is
capped when coverage is weak or probable intervention is detected. Limitations
explicitly include efficiencies, unverified inverter/BMS and import limits,
five-minute granularity, dynamic export behaviour, possible constrained solar, and
missing direct EV charger power.

Intervention evidence is intentionally probabilistic: large simultaneous grid
import/battery charge during low prices, or grid export/battery discharge during
elevated prices. It never asserts who acted or why. A future proven annotation
feature would need a separate append-only design.
