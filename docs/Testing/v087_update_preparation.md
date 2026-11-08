# v0.8.7 controlled weather update preparation

Status: local preparation only. No tag, release, image publication, production
migration, App update or activation is authorized by this document. Review the
candidate and the private rehearsal receipt before approving a release window.

## Source and operating boundary

The candidate starts from merged PR #26, main commit
`de3d2d2e8cb8683e5f5198c8432dc8f29b0ca976`. The last recorded accepted production
App is v0.8.6 on `20261024_01`; that is historical evidence, not fresh discovery.
Reconfirm the installed version, schema, owner and runtime settings at cutover.

The six new tables are `weather_collection_cycles`, `weather_response_payloads`,
`weather_page_attempts`, `weather_target_versions`, `weather_page_targets` and
`weather_collection_state`. Existing `weather_context_snapshots` is a separate
legacy context archive and must remain unchanged. Do not use a broad `weather_%`
match to identify tables to downgrade or remove.

The new version is v0.8.7. Keep both `weather_collection_enabled` and
`weather_provider_cap_confirmed` false. The provider cap option is exactly 1,000;
the local account ledger permits at most 900 attempts per rolling 24 hours.
No live key or property location is included in the candidate. Weather activation
is a separate future change, including private Linux App credential provisioning.

Preserve all existing protected options. Do not reset context, vehicle, demand,
forecast, reserve, shadow, calibration, mapping or sign settings to package defaults.
Keep hardware authority absent, non-HOLD selection false, retention disabled and
AI/Jev/SEMS live routes disabled. Solcast remains the solar forecast. No second
collector, scheduler service or cron is introduced.

## Candidate and rehearsal checks

The review packet must identify the exact merged base, complete candidate source
tree/archive SHA-256, version, Linux/amd64 image ID and dependency identities. A
local archive build must verify the archive hash and installed Python/static-file
hashes. A tree identity used before a release commit is not a published commit or
tag. Any later changed release tree needs a new build and matching validation.

Require full SQLite and owned PostgreSQL 17 regression checks, Node tests,
lint/format and the image-baked bootstrap probe. The CI workflow provisions a
separate `weather_test` database so the weather PostgreSQL variants are not skipped.
The container probe checks weather disabled defaults, private spool ownership and
0700/0600 modes, persisted receipt serialization and a synthetic spool backup/restore
roundtrip. Collector restart/database replay is checked separately by the source
tests; the filesystem probe does not establish image-baked collector replay.
Test network access must remain local; provider/HA requests are synthetic or mocked.

Use a disposable isolated PostgreSQL 17 target to prove:

1. A verified retained dump restores at `20261024_01` with every snapshot table
   count matching its receipt. Record ordered legacy row digests, schema objects,
   sequences and pending-score inventory. The retained October backup is historical;
   it does not satisfy the fresh cutover backup gate.
2. v0.8.6 starts on the old schema; v0.8.7 refuses it before migration. Upgrade as
   the intended nonsuperuser owner to `20261101_01`, preserving all legacy data and
   adding exactly six empty weather tables. v0.8.7 readiness then passes while
   weather remains disabled. No migration or weather request occurs at startup.
3. v0.8.6 refuses the newer schema. An empty-weather physical downgrade restores
   `20261024_01`; v0.8.6 readiness passes, and re-upgrade plus v0.8.7 readiness pass.
   Compare final ordered legacy digests, schema, sequences and pending inventory.
4. In a separate synthetic archive fixture, a PostgreSQL custom-format dump/restore
   preserves changed forecast versions, every page receipt, sanitized raw payload,
   original hash and RESERVED/UNKNOWN quota reservations. A nonempty weather archive
   must refuse downgrade without removing rows. Disabled reads must not claim quota.

## Fresh backup and publication gates

After review, require separate authorization for publication and the update window.
First reconfirm automatic App updates are off. Do not create or move a discoverable
tag until the exact release source/image is reviewed. Do not reuse v0.8.6 for the
new schema. Preserve the prior App image and its independent source/image manifest.

Before cutover, take a fresh consistent external PostgreSQL custom-format dump.
Capture schema revision and all application-table counts from the same exported
repeatable-read snapshot; record completion time, byte length and SHA-256. Open
connections read-only for backup and use bounded counts/lock waits. Verify the
dump inventory and restore it into a newly owned disposable PostgreSQL 17 target.
Compare all snapshot counts and the pending-score invariant; rehearse the exact
candidate migration and rollback again on that copy. Stop on any mismatch.

Keep a separate Home Assistant App backup with its protected options and persistent
`/data/weather-spool`. App backup is not an external PostgreSQL backup. A leftover
spool file is evidence, not disposable cache: preserve it, keep weather disabled,
and reconcile its reservation/receipt before any later activation. Protect backups
and manifests privately; never put credentials or household rows in Git/CI artifacts.

Check free space for dump, restore, candidate and recovery artifacts on both NAS
and NUC. The previously recorded NAS capacity warning requires fresh verification.
Local/CI installed-image hashes are not proof of the bytes installed on the NUC;
record any supported installed-build attestation and its limits honestly.

## Authorized cutover sequence (not executed during preparation)

1. Confirm exact candidate and recovery artifacts, fresh restore-tested dump and
   App backup, preserved option digest, expected role/grants and approved downtime.
   Abort on an unexpected version or revision; do not infer compatibility from age.
2. Stop the sole production App collector in the approved window. Confirm zero
   competing Windows/App collectors. Record the final observation slot and a final
   consistent dump while writers are stopped. Hash and restore-test that final
   authoritative dump, compare its own snapshot counts/inventory, and keep its
   receipt distinct from the earlier online backup. A timestamp/count checkpoint
   alone is insufficient. Complete and close all backup/snapshot reader connections
   before migration or rollback; account for this rehearsal in the approved downtime.
3. Use the reviewed release migration source with protected connection settings.
   Verify the revision before and after; do not use an unqualified moving `head`:

   ```text
   python -m alembic current
   python -m alembic upgrade 20261101_01
   python -m alembic current
   python tools/check_database.py --application-readiness
   ```

   Migration needs ownership/CREATE rights or a separately approved migrator that
   preserves the intended nonsuperuser runtime ownership/grants. Require unchanged
   legacy counts/constraints/inventory and six empty weather tables. Never stamp a
   revision or silently grant broader privileges to bypass a failure.
4. Install/start the reviewed v0.8.7 App through the supported update path with
   rollback backup enabled. Preserve every protected option and ensure both weather
   flags are false. Confirm exactly one collector, no weather requests/reservations,
   no startup migration, healthy Ingress/core collection and unchanged safeguards.
5. Observe at least two natural scheduled forecast/reserve cycles and intervening
   five-minute observations. Require linked analytical results, HOLD-only behavior,
   no command, healthy freshness/scoring and complete pending-inventory checks.
   Use fixed-ID/cutoff hashes for preservation while normal append-only writes run;
   whole-database totals will legitimately advance. Do not inject production tests.

Record actual maintenance downtime and any missed collection slots. Post-restart
continuity is the acceptance target; do not fabricate observations or describe the
offline rehearsal as proof of a gap-free live update.

## Rollback decision and commands

Stop the candidate and confirm zero collectors before rollback. Preserve a new
consistent post-update database backup and the App/spool state before any recovery.
The old App rejects `20261101_01` even when weather is disabled: App-only rollback
on that schema is not supported.

The guarded migration acquires exclusive locks on all six tables before bounded
emptiness probes and holds them until the downgrade commits. PostgreSQL uses
`NOWAIT`: any concurrent reader/writer makes rollback fail before probes or drops.
Do not weaken the lock or retry while a writer may be active. Finish/close backup
readers, confirm quiescence, investigate the lock owner and repeat only when safe.
SQLite's local-only rehearsal uses a writer reservation; it is not a production
fallback. A nonempty archive still refuses rollback under those locks.

If all six weather tables are empty and no receipt is pending in the spool, run
the reviewed candidate's explicit physical downgrade while writers remain stopped:

```text
python -m alembic downgrade 20261024_01
python -m alembic current
```

Verify unchanged legacy rows/constraints/sequences/inventory, then restore/run the
retained v0.8.6 App and original protected options. Run its own database readiness
check, confirm exactly one collector and verify advancing observations and natural
forecast/reserve cycles. This path preserves core rows written after the update.

If any weather table or spool contains evidence, do not delete it to force rollback.
The migration deliberately refuses downgrade. Keep collection disabled, preserve
the evidence and choose a reviewed schema-compatible recovery build or a separately
approved, reconciled restore. Restoring a pre-update dump can lose later household
rows and quota history; retain the post-update copy and reconcile those records
first. Do not reset quota by changing keys, deleting reservations or restoring an
older ledger. Before any later enablement after a ledger restore, establish a safe
account budget (including other consumers) and reconfirm the provider's 1,000 cap.

Never use `alembic stamp`, destructive archive cleanup or a SQLite production
fallback. No weather activation, retention cleanup, historical backfill or hardware
control is part of this controlled App update.
