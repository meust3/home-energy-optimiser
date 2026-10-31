# SEMS and AI branch reconciliation — 2026-10-31

## Scope

Base: local main `94c333d` after the test-baseline/data-quality reconciliation.
Integration branch: `codex/reconcile-sems-ai-20261031`.

Committed branch tips integrated in order:

- SEMS: `codex/sems-hca-readonly`, `76e617c`.
- Optional consumer: `codex/ai-consumer-preparation`, `af3d007`.
- Synthetic review: `codex/energy-review-pilot`, `1a4634f`.

The committed `codex/jev-energy-comparison` tip is identical to the review pilot.
Its uncommitted evaluator and adapter changes remain in their original worktree;
they were not copied into this integration. Other dirty worktrees, private
research directories and sealed historical evidence remain untouched.

This is a local merge and validation exercise. No remote branch was pushed,
production service contacted, runtime connection bundle installed, database
backfill applied, migration deployed, inference requested or device controlled.
No live SEMS/AI configuration was enabled. Existing App options and v0.8.5
release metadata are retained; the inherited migration requirement is unchanged.

## Reconciliation decisions

SEMS remains standalone, manually gated tooling, with no collector polling loop.
Its backfill tests now use the existing guarded disposable PostgreSQL selector,
so the regular integrated database suite exercises them. Synthetic apply/reverse
tests do not authorize changes to historical production eligibility or establish
knowledge-time correctness for replay. The historical 54-row backfill remains
unapproved; no household power is inferred or substituted.

The AI status route and existing arbitrage route are both retained. AI App
initialization reads only local optional configuration; absent configuration
keeps AI disabled. No worker, inference scheduler, action endpoint, model fallback
or household-data submission is introduced.

The optional Python extra pins SDK 1.0.3 at provider commit
`2aa746e42b6acea0515b099c5ba2ec986e925fc1`. This source was read from the local
Git object database, not from a mutable provider worktree or running service.
The default App build omits the SDK. The optional build accepts only an explicit
1.0.3 wheel input and requires `AI_SDK_WHEEL_SHA256`; a wheel checksum is artifact
integrity evidence, not independent provenance. No wheel is committed here.

The historical holdout quality gate remains failed: merging its tools and
receipts does not authorize active model routing or establish model quality.
Historical SDK/deployment instructions are marked as historical; the current
SDK build contract is documented at the top of the integration guide.

## Defects found and corrected

1. The synthetic review CLI used nonexistent `dataset_cases` instead of the
   report's `cases` field. Three injected-fake replay regressions reproduced
   `KeyError`; all now pass for success, failed quality and unavailable outcomes.
2. SEMS preview membership used rounded `slot_utc`, despite the specification
   requiring the actual observation instant. It now compares `observed_at_utc`
   against half-open session boundaries, preserves slot identity separately and
   rejects missing observation-time evidence. Start/end offset and missing-time
   regressions reproduced the defect and pass after correction.
3. Failed AI checks fabricated SDK version 1.0.1 through a model default. The
   default is now unknown (`null`); successful discovery still records the
   detected version. A disabled manual-check regression verifies both returned
   and persisted evidence without importing or invoking a live SDK transport.
4. The older SEMS PostgreSQL fixture remapped ORM table names without setting
   the connection's current schema. New inventory-trigger DDL therefore targeted
   `public`, causing 11 setup errors in the first complete run (1,396 passed,
   seven skipped). The fixture now uses an isolated connection search path and
   registers cleanup before schema setup. All 22 SQLite/PostgreSQL backfill
   cases pass. This correction changes tests only.

Independent standards and specification reviews found these last two issues;
both reviewers confirmed their corrections with no outstanding findings.

## Validation and isolation

Initial local SEMS suite: 90 passed, 11 skipped without a disposable PostgreSQL
URL. Initial SDK-backed AI suite: 92 passed using only fake loopback services.
The CLI/disabled-mode regression suite passed 40 tests; the combined review-fix
regression suite passed 42. Ruff, Black and all 11 JavaScript tests passed.

Full integration uses Python 3.12.11, PostgreSQL 17, SDK 1.0.3 and synthetic test
data. The PostgreSQL container has network mode `none` and no published ports;
the runner shares only that container's network namespace. Live AI is disabled
in its environment. SDK-backed tests exercise protocol handling against fakes,
not the real Panel. A superseded pre-review run was stopped before completion;
only the reviewed snapshot is used for the final full-suite result.

The final test snapshot is Git tree
`09e2fc3138df8dae75a75c6cd58d2ead6ec961ae`, image
`energy-sems-ai-tests:20261031-complete`. It differs from the App build snapshot
only in the SEMS test fixture. Ruff and Black pass across `src`, `tests`,
`tools` and `migrations` (189 Python files); build-generated copies are outside
that source scope. All 11 JavaScript tests also pass on the host Node runtime.

Final full-suite result: **1,407 passed, seven skipped in 257.18 seconds**.
The seven skips are SQLite variants of PostgreSQL-only MVCC, timeout, trigger,
locking and transactional-migration regressions; their PostgreSQL variants run.
There are no failing or errored tests. This is local synthetic validation, not
production acceptance or authorization to activate integrations.

## Build provenance

Reviewed source tree: `bf0c6826c67e24238032caee3c449743aab92f51`.
Runtime archive SHA-256:
`57776827852c2729b38bd4558f3c4ccedd4e592b056b5ebb1c0e29388e80a46b`.
Locally built pinned SDK wheel SHA-256:
`f725ef1e6356f61a9d326f49e645c3dcb7d3ef104f98fa6b682f293a93f30c46`.

Local App tags are `energy-sems-ai-app:20261031-reviewed` (SDK omitted) and
`energy-sems-ai-app-sdk:20261031-reviewed` (optional SDK installed). Neither is a
published release or deployed runtime. Credentials and private datasets are not
included in either source archive or image configuration.

Both App variants passed the image-baked bootstrap/Ingress probe: root-only
options, UID/GID 10001, secret-safe output, direct-request rejection, health and
SIGTERM handling. Each image's 90 Python/static files match canonical staged Git
blob hashes. The default image has no Panel SDK; the optional image has SDK
1.0.3. Both report AI disabled/unconfigured with no automatic processing, paid
calls or hardware commands. Network-disabled offline pilot/holdout reports in
the SDK image completed zero model calls and retained disabled routing.
