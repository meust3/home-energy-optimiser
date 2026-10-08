# Arbitrage programme candidate 0.8.0

Local candidate on `codex/arbitrage-programme-v1`, based on released v0.7.0
`c2f51838ad050e1ebfd3c843f1919206a89eb203`. Not published or installed.
The private programme state, read receipts, actual installation evidence and
approval package live outside tracked source. No installed economic claim follows.

## Working chain

The existing collector captures only whitelisted already-fetched cached telemetry,
Amber per_kwh/spot quotes and Solcast detailedForecast intervals, after its core
observation commits. It adds no Home Assistant fetch, hardware client or scheduler.
The existing forecast coordinator archives its actual demand points, bounds,
model/training metadata and linked reserve after the normal operation commits.
Each immutable capture has a separate post-commit witness, an availability upper
bound. A crash between commits leaves an unconfirmed, inadmissible capture; a
retry records its later witness rather than manufacturing earlier availability.
Target time, HA last_updated and provider issuance are distinct. Provider issue
and physical measurement time remain unknown unless supplied with evidence.

An explicitly supplied research profile is required for conditional selection.
Every capacity, efficiency, port/site limit, topology, energy domain, reserve,
state bridge and total-load scenario is declared; installed values are not filled
from application defaults. Demand remains EV-excluded baseline. Unknown future
EV/uncontrolled load never becomes zero. Named zero-load hypotheses are visibly
conditional. Profile evidence must be available at cutoff. The SOC-to-capacity
bridge is an explicit hypothesis, not measurement of the branch state.

`arbitrage_capture_enabled=false` and `arbitrage_research_profile_json=""` are the
release defaults. Empty profile blocks economics, not capture. `save_opportunity`
computes and persists advice in the existing coordinator; GET `/api/v1/arbitrage`
only reads it. The dashboard exposes expected costs, P versus R, G versus P,
G versus R, requested/delivered energy, reserve, raw captured price intervals,
provenance, source report ages, expiry and blockers. A research proposal expires
at its action start; late review cannot authorise that old action.

Observed accounting, expected candidate value and later simulated comparative
value remain separate. Outcome-v2 comparisons stay null. No executor endpoint,
command transport, live action, inference, retention deletion or new poller exists.

## Frozen research and new candidate versions

The original pure core is byte-identical and verified before offline use:
`e0c3236868079a04f4358cc0441304fc3db06bfeb4090a7326ebc920a967fe2f`.
Original designs, erratum, manifests and retained studies are unchanged.
Promoted research imports are portable under integration `arbitrage-integration-v1`.
Policy `conditional-forecast-rpg-selector-v1` remains exactly pinned at
`b35068a95f1c11bf5ee98777ef98b03ff0aae640a37dce13abd44c923746da3f`.
P needs eligible RP and CR-CP>1e-8. G needs eligible RG and PG and beats both;
P need not beat R. Whole 30-minute action, ceil5 readiness, shortest contiguous
forecast capped 24h, terminal 1e-6 kWh and energy 1e-9 kWh are preserved.
These equality tolerances are not financial thresholds.

New separately named research components:

- `arbitrage-operational-diagnostic-v1`: explicitly supplied material benefit,
  uncertainty budget, signed incremental stored-energy wear, dwell and expiry.
  Fixed diagnostic request is inherited 2 kW AC/up to 1 kWh/30 minutes, never
  installed permission. Every sensitivity scenario is retained, not tuned on holdout.
- `stored-inventory-bound-diagnostic-v1`: explicit predeclared DC inventory values;
  reports cash plus inventory bounds without restoring frozen primary eligibility.
- `continuous-state-rpg-replay-candidate-v1`: at most 350 contiguous half-hour
  origins in seven days, common realised exogenous proxies, continuously owned
  battery state per path and declared reserve equation using that state. It
  rejects SOC resets, different exogenous paths, changed physical profiles,
  missing actual input or mutated action schedules. Reports continuous cost,
  energy, loss and throughput; no overlapping episode sums or annualisation.
- `battery-ac-export-model-candidate-v1`: explicit AC request after house demand,
  PV-first shared output envelope, separate charging envelope, static/dynamic
  site caps, efficiencies, reserve and later use. New export model cannot alter
  the frozen four-action fixture CLI. Matched terminal energy and both reserves
  are required for its primary conditional verdict.
- Fake-only durable executor: approval envelope, idempotent intent identity,
  at-most-one active owner, send checkpoint, ACK separate from effect, no retry
  after ambiguous delivery, manual intervention wins. ABORTED/RESTORE_FAILED/
  UNKNOWN_DELIVERY retain ownership until neutral is verified. Any real transport
  is rejected and dispatch is disabled by default. No installed expiry is implied.

## Reproduction and isolation

Use the existing development dependencies, Python 3.12 and a separately owned
local PostgreSQL 17 database. Each full run needs a fresh database because an
existing reprocessing test intentionally writes its configured test schema.
Never point TEST_POSTGRES_URL at a shared/production service. Run `pytest -q`,
`ruff check .`, `black --check --workers 1 .`, and `git diff --check`.

The strict `tools/evaluate_paired_synthetic.py` accepts only authored fixtures.
The separate offline-only `tools/arbitrage_research.py` supports `select`,
`admit-capture`, and `evaluate`; it prohibits sockets, database connections,
subprocesses and secret-file reads. Explicit decision and outcome files are
separate; the evaluator verifies/recomputes frozen decision identity before
opening the later outcome. Outputs are exclusive-created private files.

Example:

```text
python tools/arbitrage_research.py select --decision <private decision.json> --output <new private directory>
python tools/arbitrage_research.py evaluate --decision <frozen decision.json> --receipt <immutable receipt.json> --outcome <qualified outcome.json> --output <new evaluation.json>
```

No installed-device economics or hardware command is obtained from a synthetic
pass. Risk-to-test mapping and Gate A/recovery procedure are maintained alongside.
