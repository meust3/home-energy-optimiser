# Offline Jev runner reconciliation — 2026-10-31

Base main: `5b37999`. Branch: `codex/jev-runner-offline-20261031`.
Final tested source tree: `841cf0ed8aedca868ae52c46051eb7cbb860cc0d`.
Test image: `energy-jev-runner-tests:20261031-final`.

## Scope

Implemented an offline-only experiment lifecycle with a bundled child process,
exact source/manifest/approval binding, atomic exclusive experiment claims,
durable per-case unknown reservations, deadlines and caps, no retry/resume,
typed/correlated synthetic receipts, ledger reconciliation and cleanup.

The existing offline comparison now preserves unknown attempts as a separate
count and marks rehearsal input as simulation-only. Its production-activation
boundary remains unchanged. The SDK adapter, runtime App configuration and live
submission paths are not changed. Original uncommitted Jev/SEMS files and the
previous uncommitted review report are preserved.

All execution uses synthetic data and local resources. No provider, live Panel,
Home Assistant, production database or hardware was contacted. No real credential
was read or issued, no live approval was minted and nothing was pushed/deployed.

## Validation

- Full Python 3.12/PostgreSQL 17/SDK 1.0.4 suite: **1,473 passed, seven skipped
  in 261.71 seconds**. The seven skips are SQLite variants of PostgreSQL-only
  MVCC/timeout/trigger/locking/migration checks; their PostgreSQL variants run.
  PostgreSQL was disposable, with network mode `none`, no published ports and
  tmpfs storage; the test process shared only that container's network namespace.
- Final runner/comparison tests with SDK 1.0.4 present: **51 passed**. This includes
  37 runner tests plus 14 comparison tests.
- SDK-free runner/adapter/comparison/diagnostic/App/CLI checks: **96 passed,
  11 skipped**. Skips are SDK-dependent checks; all runner tests execute.
- Ruff and Black pass over source, tests, tools and migrations (197 Python files).
  All 11 JavaScript tests also pass.
- An installed wheel was validated outside the source tree, with the SDK removed
  and Docker network disabled. The actual CLI prepared a manifest, consumed an
  explicitly synthetic offline approval, completed 48 cases, revoked its synthetic
  grant, reconciled the ledger and exited its real child. OS process lookup
  confirmed the child was gone. A repeat run was refused without changing the
  checkpoint. The comparison CLI marked the report simulation-only.
- Fault tests cover invalid/tampered manifest and approval, live-marker rejection,
  invalid budgets, reserved-cap exhaustion, actual per-case timeout, batch deadline,
  malformed/nonfinite/cross-correlated receipts, duplicate event IDs, unknown
  outcomes, single ownership under concurrent calls, startup failure, lost startup
  acknowledgement, cancellation and repeated cancellation, cleanup failures,
  missing checkpoint restart, secret isolation and output preservation.

An earlier full run was stopped after the final startup-ownership hardening;
it is not counted as final full-suite evidence. All final test snapshots use
the source tree above; later changes to the commit are documentation only.

## Standards

Independent standards review found no confirmed hard rule violations or
actionable smell findings. It identified repeated cancellation during startup
as a test target. Startup shielding, explicit child ownership and real-child
regressions now cover this path. The reviewer confirmed no outstanding
actionable standards findings after both the shielding change and the ownership
reinforcement covering startup failure after spawn.

## Spec

Independent specification review compared the implementation with the exact
published provider protocol. No confirmed violations were found within the
offline-only scope. The startup cancellation test target was addressed and
confirmed by the reviewer. Synthetic SQLite and nonce revocation are explicitly
not proof of a live owned PostgreSQL environment, provider billing, external
grant revocation or live ledger reconciliation.

Standards: zero outstanding confirmed findings. Spec: zero outstanding confirmed
findings within the offline scope; live readiness remains unestablished.

## Handover

Usage and limitations are in [the offline runner guide](../integrations/jev-offline-runner.md).
Keep the rehearsal registry intact to retain no-restart evidence. Cleanup retains
the ledger/checkpoints and stops only the runner-owned child; it never removes
other work or touches an unrelated service.
