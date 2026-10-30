# Test baseline and data-quality reconciliation — 2026-10-31

## Scope and source identity

Integration branch: `codex/reconcile-data-quality-20261031`.
Base: remote main `34bfe153b5ee83c65178d5069ab2f1fd90f976c7`.
Data-quality source: `7eddcd28c8d07dcb6585f0cbe3a6d446c88c0448` (PR #11).
Baseline fix commit: `192142b`.

This is local software integration. No production connection, migration, data
repair, hardware command, release publication, or deployment was performed.
Other worktrees and their uncommitted files were not edited. AI, Jev and SEMS
changes are not included in this integration.

## Baseline defects and regression coverage

The minimal failing collection was:

```text
python -m pytest -q tests/test_bounded_forecast_scoring.py tests/test_pending_score_inventory.py -k raw_sql_updates_scores_types_and_retention
```

It reported `fixture 'repo' not found`, although the inventory module passed
alone. Registering an already collected test module through `pytest_plugins`
made fixture discovery collection-dependent. The inventory module now imports
the fixture explicitly. A subprocess collection regression verifies both SQLite
and PostgreSQL parameterizations when the two modules are collected together.

CLI subprocesses previously imported an older installed package, producing
`ModuleNotFoundError: No module named 'energy_optimizer.arbitrage'`. An autouse
fixture now sets the child `PYTHONPATH` to this checkout's absolute `src` path.
It restores the environment after each test and does not change application
startup or install over another checkout.

## Reconciliation decisions

- Retain current-main v0.8.5 packaging, runtime constraints, release workflow,
  App options, migration files, optional arbitrage capture, and failure auditing.
- Preserve indexed pending selection, deterministic due ordering, PostgreSQL
  repeatable-read isolation, inventory locks/triggers, per-score flushes, runtime
  guards and transaction rollback.
- Add the shared actual-evidence evaluator and bounded observation batching.
  Keep existing score precedence and exact-slot/legacy interval semantics.
- Preserve scoring phase diagnostics and add duration/batch saturation metadata.
- Read the pending inventory directly for the new bounded backlog diagnostic;
  do not reintroduce the old historical anti-join.
- Integrate read-only elapsed actuals, collection incidents, canonical time
  windows, missing-value explanations, partial-day solar qualification and
  offline uncertainty review. Operational uncertainty bounds remain disabled.
- Keep the unchanged CSS cache version; invalidate the changed JavaScript with
  `0.8.5-dq1`. Update the corresponding shell test.
- Match the timeout-injection test to observation SELECTs rather than an obsolete
  column projection. The test still causes real PostgreSQL cancellation and
  verifies rollback and payload-free SQLSTATE diagnostics.

New integration regressions verify the inventory-only backlog query and atomic
recovery from interruption during batched actual lookup. Existing regressions
cover batching, negative observations, EV eligibility, legacy alignment,
immutable official scores and pending-inventory consistency.

The old v0.6.6 evidence document is retained as historical evidence with an
explicit qualification. Its original no-migration statement does not apply to
main: the inherited `20261024_01` migration still requires the established
isolated rehearsal and separate production approval.

## Validation approach

Windows validation uses Python 3.13 and local SQLite fixtures, with live/database
connection environment variables removed. Linux validation uses Python 3.12.11
and PostgreSQL 17 with synthetic data. PostgreSQL containers have network mode
`none`, no published ports and no production configuration. Test runners share
only the respective disposable container's network namespace. They use the
existing guarded `release_test` endpoint. Runtime dependency constraints are
applied when building the test image.

The initial Windows integration run reported 1138 passed, 74 skipped and one
stale asset-version assertion. After correcting that expectation, the affected
shell test and new combined-collection regression both passed (2 passed).
The earlier focused scoring/data-quality run passed 80 tests, with 30 skips.

Ruff and Black passed; all 11 JavaScript tests passed. Independent standards and
specification reviews reported no actionable findings.

Final frozen Linux integration suite: **1206 passed, 7 skipped in 302.23s**,
using Python 3.12.11, pytest 9.2.0 and PostgreSQL 17. The seven skips are SQLite
variants of PostgreSQL-only MVCC, cancellation, locking, migration and trigger
tests; their PostgreSQL counterparts ran successfully. No missing PostgreSQL
service was skipped in this final run.

```text
python -m pytest -q --tb=short -rs --durations=5
```

The initial Linux run exposed only the two stale test assumptions described
above (SQL projection and asset version). The final run includes both corrections
and the new fixture-collection regression. No production code changed between
the local App build and this successful final run.

## Local App image evidence

Image: `energy-reconcile-app:20261031` (local only).
Image identity (amd64):
`sha256:0f29d30e31105ece5dd3e7c894548b010d8edd593cc3e76022bbd5d22472eae3`.
The image revision label is the staged Git tree
`0d0fd543f19e0e6dba5813189c37625258e9a90a`, not a published commit or tag.
Runtime archive SHA-256:
`168602d150421974832c7f614bfe89db2890b2c386f42251aae0c864e13c8838`.

The full repository archive exceeded Docker's 500 KiB build-secret limit. The
successful archive therefore contains only tracked runtime/package inputs:
`pyproject.toml`, `README.md`, `requirements-runtime.txt`, `src`, `tools`,
`migrations`, `alembic.ini`, and `home_energy_optimiser`. No private datasets or
credentials were included. All 82 installed Python/static files match canonical
staged Git blob hashes; local CRLF differences were normalized separately.

The image-baked container probe passed root-only option handling, UID/GID 10001,
secret-safe output, safe shadow defaults, Ingress routing, direct-request denial,
health availability and SIGTERM propagation. This is local packaging evidence,
not deployed runtime acceptance.

## Remaining workstreams

SEMS, AI consumer, synthetic AI review and uncommitted Jev work remain separate.
Do not delete their branches or stage private research directories as part of
this integration. Frozen decision-1709 and other research artifacts are unchanged.
