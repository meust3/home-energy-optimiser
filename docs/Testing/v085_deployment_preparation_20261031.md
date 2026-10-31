# v0.8.5 App/database deployment preparation - 31 October 2026

> Superseded deployment baseline: live preflight confirmed v0.8.5 and schema
> `20261024_01` were already deployed on 25 October. This retained rehearsal
> remains historical evidence only. Follow `v086_deployment_20261031.md` for
> the authorized App update; do not repeat the production migration.

Status: preparation only; no release tag, live migration, App installation or
integration activation is authorized by this document. The candidate is based on
reconciled main `06b832749d6fc657061eb232127a7c5ffaecb974`. Runtime code and dependency
constraints are unchanged by this preparation; the release-facing prose is updated.

## Scope and release contents

- Indexed transactional pending-score inventory replaces historical selector scans.
- Elapsed actuals, collection diagnostics, missing-data explanations and qualified
  solar reporting are reconciled with current scoring/transaction guarantees.
- Standard App build excludes the optional AI SDK. AI/Jev/SEMS live integration,
  hardware execution, operational non-HOLD recommendations and retention stay off.
- SEMS session backfill, live inference, forecast model changes and hardware tests
  are outside this deployment. Existing protected options must be preserved exactly,
  including any separately accepted capture/context settings; do not blindly apply
  defaults or reset an already accepted configuration.

Retained production acceptance describes v0.8.4/schema `20261008_01`. That is dated
evidence, not a fresh production inspection. The new App requires `20261024_01`
even when optional integrations are disabled. It never migrates at startup.

## Required pre-cutover evidence

1. Identify the actual installed App, image/recovery artifact, schema and protected
   configuration through an authorized channel. Stop if they differ from the planned
   baseline. Do not print or commit credentials/options bundles.
2. Freeze the reviewed source, exact amd64 image digest and runtime dependency list;
   verify image/source identity and image-baked bootstrap checks. Publish a release
   only when separately authorized. Preparation does not create `v0.8.5`.
3. Produce a fresh recoverable PostgreSQL backup and matching source metadata. Restore
   it into an exclusively owned, unpublished PostgreSQL 17 instance. Verify all table
   counts/content, schema, constraints and indexes. The retained 17 October backup
   used for this preparation is not a fresh pre-cutover backup or current sizing proof.
4. Rehearse upgrade, runtime-role permissions, complete inventory reconciliation,
   rollback and re-upgrade against that fresh restore. Record bounded analytical
   scoring timings. Local measurements do not establish NAS throughput.
5. Confirm an approved maintenance window, recovery route and the precise migration
   role. The migration creates invoker-rights functions and does not grant runtime
   privileges. Verify the real application role can maintain the new queue; use only
   reviewed least-privilege grants if needed. Do not assume it is a schema owner.

## Controlled cutover checklist (not executed)

1. Stop the App/coordinator and other analytical writers; retention remains off.
   Confirm no concurrent writer or second collector. Retain the old App recovery
   artifact and protected configuration separately from the database backup.
2. Verify exact database identity and starting revision `20261008_01`. From the
   reviewed image, apply only `20261024_01` using an explicitly supplied protected
   database connection. Never use `alembic stamp` or relax deadlines to conceal failure.
3. Migration uses a one-second write-lock deadline, five-second statement deadline,
   10,000-ID backfill batches and a 120-second backfill budget. Any failure requires
   verifying rollback and investigating/rehearsing before another attempt.
4. With writers still stopped, require revision `20261024_01`, the pending table's
   PK/FK/due index, six synchronization triggers, two TRUNCATE guards and seven
   functions. Check enabled triggers, fixed schema references, invoker privileges
   and `pg_catalog` function search path. Compare the full inventory with the
   authoritative unscored baseline-point join in both directions, including future
   points and timestamps. Compare preexisting data counts and content hashes.
5. Verify application-role SELECT/INSERT/UPDATE/DELETE on the queue and needed
   function permissions through rolled-back tests. Run the new App's read-only
   readiness checks before starting it. No automated migration/startup repair.
6. Install/start the matching App while preserving protected options. Confirm
   no-command/HOLD-only policy, disabled retention/integrations and no duplicate
   collector. Check Ingress, five-minute collection and two normal forecast/reserve
   cycles, scoring counts/durations, pending reconciliation and safe error reporting.
   Record any maintenance collection gap honestly; do not backfill it.
7. Keep the previous recovery artifact and backup until post-update acceptance and
   the agreed monitoring window pass. An initial pair of cycles is not a long-term
   reliability, savings or hardware-readiness claim.

## Rollback and recovery (not executed on production)

Stop analytical writers. If the new schema is intact and the rehearsed rollback
conditions hold, explicitly downgrade only `20261024_01` -> `20261008_01`. This
removes derived inventory/triggers, not observations, forecasts or scores. Verify
the old revision, historical content, constraints/indexes and absence of inventory
objects, then restore the retained v0.8.4 App and its original protected options.
The old selector's historical-scan limitation returns. Old source must not run
against the new schema; never bypass readiness or change a version stamp manually.

If independent preservation checks fail, keep writers stopped and use the verified
backup restore route with separate approval and explicit accounting for any
post-backup data. Do not erase later data merely to make checks pass.

## Preparation receipts

Build identity, retained-backup rehearsal results, measured limitations and remaining
gates are recorded in `v085_isolated_rehearsal_20261031.md`. Private dumps, runtime
configuration and full database-content hashes remain outside Git. This runbook
does not supersede the mandatory safety boundary or authorize the live checklist.
