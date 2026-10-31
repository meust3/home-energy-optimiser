# Jev isolated Panel/PostgreSQL lifecycle — 2026-10-31

Base: `bcb08d0`. Implementation branch: `codex/jev-panel-lifecycle-20261031`.
Runner source digest: `9343cb53b5cee3facecd92bd4a5dff06ae1252c574a795e3446cc10045ab3017`.

The new `offline_panel_postgres` backend uses the real shared Energy adapter,
SDK 1.0.4, loopback HTTP evaluation app and PostgreSQL admission/settlement ledger.
Panel is exported from immutable commit
`3d194368db297e33049b414c4cae345e632e5dbb`; its Python/SQL source digest is
`91fdd298a362ee1d3ce5261759019b2c3d5ecd3542fc0ba5f00c664e08361914`.
No provider working files, runtime credentials or production databases are used.

The only Panel behavior replacements are offline approval reading and a fixed
provider response function. The live approval string and verified-billing claims
are never created. All answers are fixture `needs_review` responses, unrelated to
expected labels; usage and actual cost remain unknown. No real model runs.

## Executed lifecycle evidence

Standalone image built using `tools/jev-panel-rehearsal.Dockerfile`:
`energy-jev-panel-rehearsal:20261031-final`, image ID
`sha256:33d5a2b1602d2bca11786d198855eaf3548a504f25e05ee2ee0e45048ab7c0b4`.
Energy wheel SHA-256:
`bae24f1ba0c394b9c3b589a661ef838da9e17f8665b23de3d3edccb651f0650a`.
PostgreSQL 17 image ID:
`sha256:7958605b474b3d264a969cb3a123d6aa00ad1e1fe9da8a69984dabb704d93317`.

| Experiment | Runner outcome | Attempts | Retained synthetic reservation |
| --- | --- | ---: | ---: |
| `1d3ee5a7-2fc0-41b6-9277-9426424fddfa` | completed, fixed mocked responses | 48 | USD 0.12902400 |
| `8ccbf6fa-302b-4912-9b86-284e04ca11f9` | partial, simulated provider timeout | 1 unknown | USD 0.00268800 |

Both runs verified PostgreSQL event/request reconciliation, duplicate rejection,
temporary grant revocation and HTTP 403 enforcement, synthetic SQLite checkpoint
reconciliation and owned child termination. Both removed their own two containers.
The timeout run made no retry. Panel requests remain `incomplete` because usage is
unknown even where fixture evaluation answers completed; monetary reservations
remain intact. No cost or billing conclusion is inferred from the synthetic ledger.

Receipts are retained locally under
`%TEMP%/energy-jev-panel-20261031/evidence/<experiment>/lifecycle.json`, alongside
offline manifests, offline approvals and runner checkpoints. Sanitized PostgreSQL
ledger metadata survives removal of the ephemeral database. Earlier development
attempt receipts remain intact; failed attempts were never resumed.

## Regression validation

- Full Python 3.12/PostgreSQL 17/SDK 1.0.4 suite: **1,506 passed, seven expected
  SQLite-only variant skips in 358.04 seconds**. PostgreSQL variants executed.
- Final focused runner/lifecycle suite: **72 passed**, including **22** new
  ownership/refusal/cancellation/cleanup tests. These include
  interrupted container creation, wrong-owner cleanup refusal, inherited live
  configuration, non-loopback namespace refusal, failed startup/submission,
  cancellation, revocation despite HTTP cleanup-probe failure, and closing a
  refused nonempty database without cleanup writes. The last two regressions and
  final nonempty-database fix were checked by this focused run after the full
  suite had collected; both final standalone scenarios also exercised the final code.
- SDK-free regression selection: **102 passed, 23 SDK-dependent skips**.
- Ruff passed across source/tests/tools/migrations; Black checked **203 files**.
- Both standalone image scenarios passed with external networking disabled.

An initial full-suite command used the wrong disposable PostgreSQL role/dialect;
the existing guard refused it. That run was stopped and its owned database removed.
The corrected run uses the required `release_test` role/database and
`postgresql+psycopg` driver. Initial wheel packaging needed the cached setuptools
build backend; the subsequent wheel and standalone image builds passed.

## Preservation and scope

All seven original uncommitted Jev/SEMS files matched the prior preservation hashes.
The existing untracked `remaining_wip_review_20261031.md` is excluded from this
change. Main's AI adapter/diagnostic implementations and default disabled runtime
configuration were not edited. No old SEMS work was reconciled in this increment.
No push, deployment, production migration, paid inference or live integration
request was performed. Container cleanup is restricted to recorded owned resources.

This establishes an offline lifecycle rehearsal, not live Jev compatibility,
verified billing, model quality or production readiness. Live execution remains
disabled. See the [runner guide](../integrations/jev-offline-runner.md) for use and
the exact isolation and evidence limits.
