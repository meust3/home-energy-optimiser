# Synthetic AI decision-review pilot — 3 October 2026

Implemented as an explicit development replay using the existing optional adapter.
The collector, forecast/reserve arithmetic, shadow recommendation selection, dashboard
and Home Assistant runtime do not import or schedule this pilot. No production database
or household observations were used. No hardware or paid provider calls occurred.

## Published provider contract

The panel owns task version 1.0.0, its eight synthetic case snapshots, review question,
route policy and permission/admission checks. Source and SDK 1.0.2 were published at
`4c821193f4c406ddedcc077fd29459e3c435c98d` on `codex/energy-review-pilot`:

- `contracts/energy-review-v1.json`
- `docs/integrations/energy-review-pilot.md`
- `packages/client-python/panel_energy_review.py`

The Energy AI extra pins that immutable remote SDK commit. There is no mutable sibling
import. SDK 1.0.1 still supports the earlier diagnostic path; synthetic review requires
1.0.2. Existing production candidate image/source/wheel remain the previous release;
this pilot does not update its Dockerfile or claim a production-ready image.

`POST /v1/integration/tasks/battery-review` accepts only task_version, case_id and a
caller-retained operation UUID. The application selects a task/case, never a model.
The panel selects bounded-local under `energy-review-local-v1`; there is one authorised
route in this pilot. Unknown cases, arbitrary context, questions, labels and provider
overrides are rejected. No automatic escalation, retry or cloud fallback exists.
Build/test/production credentials and other projects cannot invoke it. It uses the
existing backend development diagnostic grant and local scope without widening grants.

The app checks authenticated project/caller/environment, task/hash/route catalogue,
pause/permission/worker readiness, receipt identity, metadata acceptance and typed
answer bounds. Stable per-case UUIDs derive from the retained root UUID and dataset
hash. A repeated case returns a receipt without answers; uncertain inference is never
automatically retried under a new UUID. Failed calls stop the batch and remain failures.

Raw model judgements are retained for evaluation. The review disposition cannot clear
an existing deterministic missing-evidence or constraint/tradeoff review flag. It does
not alter the shadow action, data-health gates or battery reserve. High confidence is
not treated as calibrated correctness or permission.

## Actual runtime evaluation

An isolated Uvicorn panel process on PC loopback used `ai_control_panel_test`, a
temporary scoped test credential and the actual shared Mapika GPU worker. A separate
Energy Python CLI process used the installed SDK from the exact remote commit. The
eight corresponding fixture event IDs were independently checked in the isolated
PostgreSQL ledger, including task/hash, live-local backend and fixture exclusion.
This was real model execution through the app's adapter; it was not a NUC-origin test
or deployment of the shared running panel.

Root operation: `db81ea8b-92f1-4f80-8ca3-510ed0cf1224`.
Model: `Mapika/decider-4b`, revision
`eb5fbdfc9448473ec25e399882912863afbdb70e`.

| Measurement | Result |
| --- | --- |
| Completed model requests | 8/8 |
| Correct hand-authored review labels | 7/8 |
| Deterministic baseline labels | 8/8 |
| Reported local input tokens | 1,669 |
| Total CLI adapter elapsed time | 5,617.494 ms |
| Paid requests | 0 |
| Local electricity cost | Unknown |
| Calibration / economic decision quality / savings | Not established |

The model incorrectly labelled `reserve_violation` as supported (confidence 0.8232).
The fixture states 5 kWh after export against 12 kWh required reserve. Trace:
`abddaaf2-edc3-41d5-8001-6c293499ad23`. The expected result remains needs_review.
This is a material failure and is retained as evidence; the label was not changed or
prompt tuned to hide it. A consumer regression test verifies that even confidence 1.0
cannot clear the deterministic review flag. The guarded disposition was added after
the first live pass and is separately unit-tested; the saved original live report
retains the model result as returned.

These eight deliberately simple fixtures test review semantics and protocol flow.
Their structured flags make them solvable by exact rules; no model advantage is shown.
They do not establish general accuracy, economic benefit, measured battery safety or
an optimal router. A larger independently labelled held-out set and evaluated routing
policy are required before a model receives authority over recommendations.

## Usage

Install the optional AI extra from this checkout. Default replay is offline and invokes
no model:

```powershell
.\.venv\Scripts\python.exe -m tools.ai_review_replay
```

An explicit developer replay against a panel that has this task deployed:

```powershell
.\.venv\Scripts\python.exe -m tools.ai_review_replay --config .env.ai-control-panel --run --operation-id <retained-UUID> --output .local/ai-control-panel/review.json
```

Exit 2 records unavailable/denied/duplicate/incomplete/incorrect results. It must not
be treated as a transport failure when the replay completed but a label was wrong.
The existing shared panel is not updated by this task, so its current catalogue will
report this new task as pending until the provider candidate is deployed.

For reproducible isolated runtime verification, the panel branch supplies
`scripts/verify-energy-review-runtime.py`. It accepts only the fixed loopback test DB,
starts/stops its own child API process, provisions/revokes only a temporary test key,
and invokes the real Energy CLI. Run after test suites have finished, never concurrently
with schema-resetting panel tests. The original local reports are in this checkout's
ignored `.local/ai-control-panel/energy-review-20261003.json` and `.runtime.json`.

## Deployment disposition

Verification: the Energy checkout suite passed 504 tests with 15 optional tests
skipped. The focused AI integration suite passed 87 tests; the subsequent guard
regression passed with the 18 review tests. Changed-file Ruff and Black checks passed.
The provider's isolated PostgreSQL suite passed 112 tests with one optional recovery
skip; ten frontend tests/build and the local candidate image build/import passed.
These software checks are separate from the 7/8 live model-label result above.

Active routing stays disabled. The panel task is published on a candidate branch;
the shared panel service and Home Assistant NUC were not replaced or restarted.
Production inference remains discovery-only under the existing contract. Future
deployment needs the panel's normal backup/restore procedure, edge route update and
actual NUC-origin transport verification. Multi-model/cloud routing additionally
needs a published task policy revision, evaluated eligibility and explicit scope,
privacy and spending limits. This pilot is not a reason to change those policies.
