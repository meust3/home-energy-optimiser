# v0.8.5 isolated deployment rehearsal - 31 October 2026

> Superseded deployment baseline: live preflight confirmed v0.8.5 and schema
> `20261024_01` were already deployed on 25 October. This retained rehearsal
> remains historical evidence only. Follow `v086_deployment_20261031.md` for
> the authorized App update; do not repeat the production migration.

Status: **local preparation passed; not deployed or published**. Production was
not contacted. Live AI, SEMS, Jev and hardware integrations remain disabled;
no production options, data or services were changed.

## Prepared artifact

- Source: `6cd6e824f031855b3bc260c6378a11546a2a9a37`, on local branch
  `codex/v085-deployment-preparation-20261031`, based on reconciled main
  `06b832749d6fc657061eb232127a7c5ffaecb974`.
- Image: `energy-deploy:0.8.5-6cd6e82`, linux/amd64, optional SDK omitted.
- Image ID: `sha256:230bf85fe42cbafc3ce58ddd5105e05f8b3cd43acea02043d100d8bf16cb998d`.
- Source archive SHA-256:
  `8c002562ca36253421fe23839c574c712d027a1c898e394808a8bb81775cfac2`.
- Saved image archive SHA-256:
  `61e6cf81331ff6444987794d0af7c1409f770a37dbfdce5238a2539796497d01`.
- All 97 installed application Python/static files matched the source archive.
  `pip check` passed; the optional SDK distribution is absent. Dependency inventory
  and source archive are retained with the local package.
- Image-baked bootstrap checks passed with every test container forced onto
  `--network none`: UID/GID 10001, root-only options handling, secret-safe output,
  trusted Ingress, direct-request denial, health endpoint and SIGTERM propagation.

This report is a documentation-only follow-up to the frozen build commit. It does
not change the candidate runtime. No release tag or remote branch was published.

## Database evidence and isolation

Used the retained v0.8.4 verification dump from 17 October, snapshot time
`2026-10-17T02:55:45.463132+00:00`, starting at `20261008_01`.
Its SHA-256 is
`52b915644ae19081290114573fcc89d5701e7de8b3bd5eebafdfc007f54f0610`.
This is historical household evidence, **not a fresh pre-cutover backup**.

The dump was mounted read-only into a uniquely labelled PostgreSQL 17 container
with no external network or published ports and temporary database storage.
The candidate App's Python process shared only that container's loopback network.
No production connection variables or Home Assistant credentials were supplied.
All owned database containers were removed after their attempts; original dumps
and existing work were preserved. Raw database rows were not copied into Git.

The restore matched the retained table counts, including 21,425 observations,
3,164 forecast runs, 910,703 forecast points and 903,602 scores. Full ordered row
digests for all 20 historical tables, existing column/constraint/index definitions
and sequence values were compared before/after every successful schema transition.

| Final complete attempt | Result |
|---|---|
| Restore | Passed, 31.74 seconds |
| Upgrade to `20261024_01` | Passed, 43.76 seconds |
| Historical data/schema/sequences | Exact preservation after upgrade, downgrade and re-upgrade |
| Pending inventory | 7,101 rows; zero differences against authoritative unscored baseline points in either direction |
| Inventory objects | Valid due index, eight enabled triggers, seven invoker-rights functions with `pg_catalog` search path |
| Downgrade to `20261008_01` | Passed, 0.061 seconds; derived queue/functions/triggers removed |
| Retained v0.8.4 App readiness after rollback | Passed using the non-owner runtime fixture |
| Candidate App readiness with explicit grants | Passed on a separate restored/upgraded copy using the non-owner runtime fixture |
| Re-upgrade | Passed, 0.884 seconds; inventory reconciled again |
| Bounded scoring using non-owner/non-superuser role | 235 scores in 0.139 seconds; queue 7,101 -> 6,866; zero duplicate scores; full inventory reconciliation passed |

These timings are local measurements on a retained snapshot. The large difference
between first upgrade and re-upgrade is not a NAS performance guarantee. Scoring
used a 2,500-point cap but only 235 points were eligible at the snapshot time; this
does not establish maximum-batch throughput. Analytical writes affected only the
disposable restored copy.

## Failures retained and operational implications

- An initial harness isolation check miscounted an empty Docker port-binding
  object. It stopped before restore and removed its owned container. The harness
  check was corrected; no application code or migration limits changed.
- The first database attempt passed upgrade and rollback, but re-upgrade hit the
  one-second lock deadline. Its failed receipt is retained. The repeat recorded
  background autovacuum activity and waited for maintenance to quiesce before
  migration. The original blocker was not captured conclusively. Migration lock,
  statement and backfill deadlines were never relaxed. Live maintenance planning
  must account for background maintenance as well as application writers.
- A deliberately separate, non-owner runtime fixture passed rolled-back trigger
  and queue DML checks after explicit grants. Downgrade drops the queue and its
  grants. After re-upgrade, the App readiness probe correctly failed with queue
  permission denied before grants were reapplied. Scoring passed after the harness
  reapplied the grant. Automatic teardown preceded the full readiness recheck, so
  a separate restore/upgrade repeated the explicit fixture grants and captured a
  passing full candidate-App readiness report. That owned container was also removed.
- An earlier readiness probe ran before the fixture role existed and refused
  connection. Both unsuccessful probes are retained, not reported as passes.
- Fixture grants demonstrate functionality, not the production role's privileges
  or a complete production least-privilege audit. No production grants were read
  or changed. Verify the actual role and explicitly review any necessary grants.

## Regression validation and preservation

The exact source's `test_pending_score_inventory.py`,
`test_bounded_forecast_scoring.py` and `test_check_database.py` passed in a second
owned PostgreSQL fixture and SQLite: **83 passed, 7 skipped**. The seven skips are
SQLite cases for PostgreSQL-only trigger, MVCC, timeout and transactional semantics;
their PostgreSQL counterparts ran. Containers had no external network. Existing
full-suite validation on reconciled main remains prior evidence; it was not rerun
or represented as new evidence for this documentation-only preparation.

Seven previously recorded uncommitted Jev/SEMS file hashes still match. Existing
untracked branch-assessment and WIP-review documents were left uncommitted.

## Local handover and remaining deployment gates

The ignored `.local/deployment-v085-20261031/` directory holds the image archive,
source archive, dependency list, validation scripts and receipts, including failed
attempts. It contains no new copy of the database dump. Keep this local package
with the separately retained backup/recovery artifacts; do not publish private
evidence. Scripts reference the original local rehearsal paths and are evidence,
not unattended production deployment commands.

Follow [the deployment runbook](v085_deployment_preparation_20261031.md) before any
separately authorized cutover: confirm actual installed state and protected options,
take a fresh backup, repeat isolated restore/migration/rollback with current data,
verify actual runtime-role privileges and full App readiness, identify the recovery
artifact, and agree the maintenance window. Release publication, production
migration, App installation and live acceptance remain unexecuted.
