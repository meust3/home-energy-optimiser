# Offline replay and evaluation follow-up - 31 October 2026

Base: `origin/main` at `2fe5e3a360411cac6e752f8e94b756f94666825a`.
Working branch: `codex/offline-replay-evidence-20261031`.

## Implemented replay boundary

New reusable `frozen_training` functions serialize explicitly supplied original
observations and verify checksum, capture/decision ordering, sample timestamps,
explicit eligibility/health, finite demand, duplicate slots and size bounds.
The thin `tools.replay_demand_population` CLI runs the existing estimator from
those bytes, requires an explicit original-manifest digest and refuses existing
outputs. It cannot open configured databases, collect telemetry or apply a plan.
Rows are reparsed on every load, so caller mutation cannot alter retained bytes.
UTC metadata is normalized while original observation fields remain intact.

The trusted external manifest and truthful capture/source provenance are caller
preconditions. Checksums do not authenticate dates. Output explicitly retains
`provenance_verified=false`; unavailable original evidence must stop historical
studies, not trigger a current-database fallback. See the
[input contract](../integrations/frozen-training-replay.md).

No existing collector, scheduler, repository reader, forecasting arithmetic,
configuration, migration or SDK pin was modified. Legacy mutable-history readers
remain unsuitable as automatic knowledge-time reconstruction. No production
backfill is authorized by this work.

## AI preparation

A separate model-based reviewer, blinded to author labels and model outputs,
reviewed the eight original narratives against project policy. All eight labels
agreed with the frozen author labels. This is policy review, not independent
human expert validation. The failed Mapika quality result remains unchanged.

The [evaluation preparation](../integrations/ai-evaluation-preparation-20261031.md)
and [design template](../integrations/ai-next-holdout-design-20261031.json) specify
32 new cases / 16 correlated family units, separate oracle/label custody, an
independently frozen manifest, unchanged quality gates and bounded no-retry
execution requirements. They explicitly remain `DRAFT_NOT_EXECUTABLE`:
new corpus authoring, independent human adjudication, unexposed-status validation,
dataset freeze, provider/billing checks and execution approval are pending.
There was no new model or paid provider execution.

## Superseded PRs

- [PR #10](https://github.com/meust3/home-energy-optimiser/pull/10) closed without
  merging, referencing the AI reconciliation in `11d1bc7` / PR #21.
- [PR #11](https://github.com/meust3/home-energy-optimiser/pull/11) closed without
  merging, referencing data-quality reconciliation `94c333d` / PR #21.

Each received a supersession comment. No branch/worktree was deleted or altered.

## Validation

- Red/green slices first reproduced absent replay interfaces, then exercised
  real SQLite fixtures. Final focused SQLite/PostgreSQL 17 selection:
  **109 passed in 61.95 seconds** across immutable population, SEMS backfill and
  reserve tests. Both database variants of all new regressions executed.
- SDK-free container check: **11 passed, 11 PostgreSQL-only skips in 15.52
  seconds**. SDK 1.0.4 was uninstalled only in that disposable `--network none`
  container and `panel_client` absence asserted before execution. The host's
  existing optional SDK installation was discovered and left unchanged. The
  skipped PostgreSQL variants had all executed in the 109-pass isolated run.
- The new regressions place the decision strictly before SEMS context knowledge,
  then prove population identity through later apply, reverse and a separate
  manual annotation. Forecast output is invariant under later database changes.
- Refusal checks cover late capture, changed bytes, duplicate/future/naive/missing
  sample evidence, nonfinite demand and output reuse. UTC and missing demand are
  preserved. CLI success/refusal subprocesses use no credentials or runtime bundle.
- PostgreSQL ran in a uniquely labelled owned container with `--network none`,
  tmpfs data and no published ports. Test runtime shared only that namespace,
  read-only source and explicit synthetic `release_test` configuration. Owned
  PostgreSQL resources were removed in a guarded finally block. No production
  database or provider was reachable from this test namespace.
- One initial database command named a nonexistent forecast test file and ran
  no tests; it was corrected to the existing reserve suite. Its owned database
  was cleaned up. Formatting-related fixture lint annotations were corrected.
- Ruff and Black pass for all three new Python files. Independent Standards and
  Spec reviews found no outstanding defects under the stated provenance contract.

All seven original Jev/SEMS hashes and the three pre-existing untracked review
reports remain unchanged. Existing source worktrees/private evidence were not
edited, staged, archived, committed or pushed. This report records the completed
local implementation stage; publication validation is recorded separately against
the final PR commit. No production access, integration activation, hardware
command, App update or retention change occurred.
