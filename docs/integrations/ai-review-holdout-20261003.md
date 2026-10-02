# Expanded synthetic review evaluation — 3 October 2026

The actual local model failed the predeclared review gate. All 48 requests completed
through Energy's adapter and the pinned SDK, an isolated Uvicorn panel process, the
real shared Mapika GPU worker and `ai_control_panel_test`. Forty-eight fixture ledger
events were independently correlated with the returned event IDs. No production data,
production database, paid calls, NUC deployment or shared service replacement occurred.

## Frozen inputs and labels

Task 1.1.0 and compatible SDK 1.0.3 were published before inference at provider commit
`2aa746e42b6acea0515b099c5ba2ec986e925fc1`. The Energy AI extra installs that exact
remote revision in this worktree's separate virtual environment. The original task
1.0.0/cases remain supported. This run used the original unmodified Choice question.

Provider sources: `contracts/energy-review-holdout-v1.json`,
`packages/client-python/panel_energy_review_holdout.py`, and
`docs/integrations/energy-review-holdout.md`. Cases and question have published hashes.
No prompt adjustment, threshold tuning or label change followed the model outputs.

Forty numerical cases have scenario-specified labels checked against a separate
numeric oracle. Eight paired narrative cases have author-specified labels and still
lack independent expert review. This is independence from model outputs, not an
independent human labelling study. State omits labels, outcome/feasibility flags,
baseline results and label provenance. The original eight pilot cases are excluded.

The conservative rule baseline matches all numerical labels and defers all narrative
explanations to review, matching half of their labels. It is a synthetic reference,
not measured production optimiser accuracy. The designed stress set is small and
non-random; four variants per numerical family are correlated, not 40 independent
samples. Do not generalise its accuracy or fit confidence thresholds to this set.

## Results

| Stratum | Cases | Correct model labels | Correct baseline labels | False model-supported labels |
| --- | --- | --- | --- | --- |
| Numerical | 40 | 15 | 40 | 20 |
| Narrative | 8 | 1 | 4 | 0 |
| Total | 48 | 16 | 44 | 20 |

The predeclared gate required zero false-supported labels and at least baseline
correctness overall and in each stratum. Both quality conditions failed. Independent
expert label review is also still pending. Active routing and production inference
remain disabled. No other model/provider was tested, so these results do not assess
Jev, general/premium aliases or cloud compatibility.

Root operation UUID: `2f7cd807-0448-4c8d-8c74-b34516b11e9d`.
Model: `Mapika/decider-4b`, revision
`eb5fbdfc9448473ec25e399882912863afbdb70e`. Actual reported local input: 13,844 tokens.
Total adapter elapsed time: 27,798.305 ms. Forty-eight attempts stayed within the
48-attempt/120-second budget. No retries/fallback/escalation occurred. CLI exit 2
means the evaluation completed but quality failed; it does not indicate a connection
failure. API spend was zero; local electricity cost remains unknown. Calibration,
real economic benefit and savings are not established.

For example, h32 is a BLOCKED proposal with complete, healthy numerical evidence and
no stated reason to block. The specified label is needs_review; the model returned
supported at confidence 0.8853, trace
`05827500-4d55-4c6f-a231-62968e0e6326`. Missing price/Solcast coverage and low-solar
reserve/comparison cases also produced false supports. Confidence did not repair
these errors and no post-hoc threshold is presented as validation.

All twenty false-supported numerical results retained the deterministic review floor
in the evaluation disposition. The raw model answer and probabilities remain intact
for audit. This disposition never changes the battery action, reserve, data health,
forecast, controls or dashboard. Narrative baseline deferral is distinguished from a
numerical constraint failure, so raw narrative results can be evaluated without
asserting that the rule baseline understands their meaning.

Full metadata-only results: [result record](ai-review-holdout-results-20261003.json)
and [process/ledger verification](ai-review-holdout-runtime-20261003.json). These contain
fixed case/label identifiers, typed outputs and traces, never model input text,
household observations, credentials or database connection strings.

## Reproduction and checks

Offline inspection performs no network/model call:

```powershell
.\.venv\Scripts\python.exe -m tools.ai_review_replay --suite holdout
```

A deliberate run against a panel with this candidate task deployed:

```powershell
.\.venv\Scripts\python.exe -m tools.ai_review_replay --suite holdout --config .env.ai-control-panel --run --operation-id <retained-UUID> --output .local/ai-control-panel/holdout.json
```

The provider's `scripts/verify-energy-review-runtime.py --suite holdout` reproduces
the isolated process path. It creates/revokes only a temporary test key and starts/
stops only its child API; its DB target is fixed to loopback `ai_control_panel_test`.
Do not run it concurrently with panel tests that reset the test schema. The adapter
has a 120-second batch deadline; expired or failed requests stop the batch, retain
their operation IDs and never trigger automatic retries.

Verification: the clean Energy worktree suite passed 478 tests with 15 optional
skips. The subsequent focused AI suite passed 92 tests, including the new exhausted-
deadline regression. Changed-file Black/Ruff checks passed. Provider PostgreSQL
suite passed 117 tests with one optional recovery skip; frontend and candidate image
build/import passed. A new isolated environment was used; the original Energy
checkout's dependency environment and concurrent source work were not updated.

## Disposition

Keep exact energy checks and calculations in normal code. This local model/task/input
version has not demonstrated a useful improvement over that reference and must not
receive decision authority or active routing. Preserve this version as a regression
set. Any revised question, input representation or candidate model needs a distinct
version and a fresh unseen evaluation set; this exposed holdout cannot remain held
out after tuning. Any paid model comparison needs explicit bounded permission and a
published provider task policy; no cloud request is authorised by this evaluation.
