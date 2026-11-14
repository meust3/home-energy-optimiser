# v0.8.9 controlled dashboard update preparation

Status: local candidate for review, not approval to publish or deploy. Production,
weather collection and the 1,000-call provider cap must remain unchanged until
the operator approves the update. Do not stop the writer during preparation.

## Candidate and compatibility

Merged dashboard fixes: PR #31, `e30070fef4d89361fd8c50a08ea0f725ec6774d9`.
Validated PR head: `f995b6dfd8aa6c2acc1c7ad1d546a8f806117e31`.
[PR CI](https://github.com/meust3/home-energy-optimiser/actions/runs/43543472231)
passed 1,550 Python tests (35 skipped), 20 frontend tests, the amd64 App build,
bootstrap and installed-source checks. That build used version 0.8.8. This local
candidate advances the package, runtime, Docker defaults and CI build version to
0.8.9; it needs its own exact-commit CI and image validation before deployment.

The application changes since accepted v0.8.8 are dashboard presentation assets.
There are no migration, dependency, repository, weather parser, spool, ledger,
collector, demand-model or option-schema changes. Expected schema remains
`20261101_01`. No upgrade, downgrade, stamping, repair, replay or backfill is
required. Unexpected live schema or source identity blocks the update.

Preserve every saved option, including enabled weather collection, ten-minute
cadence, confirmed 1,000/day provider cap and the 900-attempt rolling local guard.
Do not apply new-install defaults to the existing installation. Weather remains
context only and does not replace Solcast or activate demand adjustment.

## Evidence and limits

Local preparation evidence is private under `.local/preparation/`. No credentials,
household database, screenshots or private manifests belong in Git or CI artifacts.
The retained backup rehearsal uses the 13 November recovery set; it cannot prove
current backup freshness or preservation of records collected since then.
Synthetic old/candidate/old captures exercise completed archive compatibility,
not recovery of an arbitrary interrupted provider request.

Preparation results on 14 November:

- Retained 13 November PostgreSQL dump integrity and new isolated PostgreSQL 17
  restore passed: 28 table counts, 11 critical ordered row hashes, schema
  equivalence, application-role access and 12 exact sequence states. Temporary
  restore server stopped. This did not test production role-password recovery.
- Synthetic SQLite v0.8.8 → v0.8.9 → v0.8.8 capture rehearsal passed, preserving
  earlier archive rows and 192 targets per capture, with zero provider requests.
- Candidate tests: 111 Python passed, 27 PostgreSQL-dependent skipped; 20 frontend
  passed; focused Ruff/Black checks passed. An earlier sandbox test run stalled
  and was stopped; the permitted local test rerun completed successfully.
- First restore attempt failed to connect under sandbox restrictions and stopped
  its owned server. The permitted local-loopback rerun passed as described above.
- Remote main matches the merged dashboard commit, v0.8.8 points to the accepted
  source, and v0.8.9 was absent at preparation. No publication was performed.
- Local Docker Linux engine is unavailable. The v0.8.9 image build/bootstrap and
  installed-byte comparison remain pending exact-candidate CI. The prepared CI
  comparison now includes dashboard static assets as well as Python source.
- Current production runtime, automatic updates, private option equality and
  actual installed v0.8.8 recovery image have not been freshly verified this turn.

Recorded v0.8.8 acceptance is historical evidence. Fresh installed version,
automatic-update state, option equality, runtime health, free space, actual image
identity and recovery availability must be checked again before approval/cutover.
Do not label those current PASS based on previous records.

## Before requesting update approval

1. Review and commit the complete v0.8.9 candidate; run exact-head release CI.
   Confirm automatic App updates are off before any version publication.
   Public tag/release publication requires explicit authorization. The Dockerfile
   expects `v0.8.9`; a missing tag is a release gate, not permission to build main.
   Pin the eventual tag to the reviewed release commit and verify archive/image
   identities, including installed static files, not just Python modules.
2. Privately compare the current options to an encrypted before snapshot without
   printing or separately hashing credentials. Record only safe equality results.
   Check the existing cap setting without a forecast request. Preserve the known
   usage discrepancy; never alter reservations to force provider-ledger agreement.
3. Check NAS, NUC and local recovery space. Identify the actual installed v0.8.8
   image and a supported rollback route. Old v0.8.7 backups are not v0.8.8 rollback
   evidence. A source archive alone cannot restore App data or the installed image.
4. If taking an online rehearsal backup, use a consistent exported read-only
   PostgreSQL snapshot with bounded lock/statement timeouts. Record dump length,
   SHA-256, schema and counts from that same snapshot. Keep it distinct from the
   final stopped-writer backup. Avoid a second collector or provider request.

## Approved maintenance sequence (not executed in preparation)

1. Reconfirm approval, immutable release/image identities and all preceding gates.
   Observe a natural weather cycle finish and drain receipts under v0.8.8, then
   stop the sole App writer through the supported interface. Keep weather options
   enabled; stopping the process is not a configuration change. Record downtime.
2. With the writer stopped, inventory the entire spool, including temporary and
   unexpected files and symlinks. Reconcile RESERVED attempts and COLLECTING cycles.
   A pre-stop empty-spool check has a race and is insufficient. Preserve UNKNOWN
   attempts as charged. Unexplained pending work blocks cutover; never discard it.
   Verify no competing Windows/App collector or other database writer remains.
   Identify other sessions before backup and close the rehearsal/backup readers
   before installation. Do not infer sole-writer status from the App UI alone.
3. Capture a fresh coherent recovery set: supported App backup with actual v0.8.8
   image, protected options and `/data` (credentials and spool), plus an independent
   external PostgreSQL dump. App backup is not a PostgreSQL backup. Verify backup
   access/inventory and retain private role-recovery information separately: a
   database dump does not retain cluster passwords.
   Bind the App backup identity, dump SHA-256 and length, snapshot timestamp,
   options-equality receipt, spool inventory, frozen primary keys and source
   image identity in one private recovery manifest. Recheck artifact integrity
   immediately before restore; never reuse a preparation PASS for new bytes.
4. Restore that fresh dump into a new owned, loopback-only PostgreSQL 17 instance.
   Verify all table counts, schema/constraints/indexes, ownership/application-role
   privileges and exact stopped-source sequence states without advancing them.
   Compare ordered hashes for observations, revision, all seven weather tables,
   context observations and derivations. Verify frozen primary-key multiplicity.
   Require the complete expected table/hash inventory before reporting PASS,
   and verify the source-schema witness digest. Include demand forecast runs,
   points and scores in the fresh archive witness; the retained rehearsal's
   eleven hashed tables did not establish their value-level equality.
   Confirm the owned restore server stops. Any failure blocks installation.
5. Check both v0.8.8 and v0.8.9 readiness on the expected schema without starting
   collectors against the restored household database. Perform no migration.
6. Install the approved v0.8.9 App. Verify source/version, unchanged schema and
   exact option equality; confirm only one coordinator/writer. Observe normal
   five-minute observations and the next naturally scheduled weather cycle.
   Verify retained reservations, every forecast version and existing context
   repairs. Compare immutable pre-update rows by frozen keys; separately explain
   legitimate mutable state transitions and new appended records.
   Compare frozen records by primary key and row multiplicity, not just membership
   of content hashes. Separate append-only forecast versions from legitimately
   changing score/operation/collection state and reconcile each permitted change.
7. Exercise all eleven screens, rapid filters, hidden/visible recovery, selected
   forecast runs, accuracy-limit warning, weather as-of selection and narrow
   layouts. Confirm new asset identifiers. Record the maintenance gap without
   fabricated backfill. Leave automatic updates off and hardware control absent.

## Rollback without losing newly collected history

Prefer a code/image rollback to verified v0.8.8 against the CURRENT database.
The schema and weather serialization are unchanged. Drain receipts, stop the
writer and repeat stopped-spool/reservation checks before restoring the old image.
Take and verify a new coherent recovery set of the current state before rollback;
the pre-update backup alone does not protect records appended under v0.8.9.
Preserve current options, archive, repaired context, receipt bytes and quota ledger.
Reverting restores the previous dashboard defects; it does not undo observations.

A full App restore may overwrite newer `/data`. Review and reconcile its options
and spool against the current database before using it. Never overwrite newer
history with the pre-update dump, downgrade a populated weather archive, clear
receipts, refund uncertain calls or run a second collector. Disaster database
restore is a separate explicitly reviewed recovery decision accounting for every
post-backup write. If drainage or coherence cannot be established, preserve the
stopped recovery state and report the blocker rather than starting the old writer.

## Preparation review corrections

The private restore harness now rejects incomplete hash/table witnesses before
it can report PASS, verifies the schema-witness digest and rejects optimized
Python execution that would remove its assertions. The recorded first rehearsal
did contain all required hashes; this correction closes a false-PASS path for a
future incomplete witness rather than invalidating the retained data.

The private rollback rehearsal now enforces the accepted v0.8.8 commit and clean
source/test files, rejects unexpected Python sources, asserts phase versions,
orders snapshots by primary key and compares hash multiplicities. Its former
mutable-directory assumption and membership-only comparison were insufficient
as reusable rollback evidence. Original evidence is retained separately.

The App backup checks remain inventory/identity checks until supported image/data
restore has been rehearsed. Database privilege checks inspect restored role grants;
they do not prove authentication with production credentials. Neither limitation
is permission to skip recovery verification in the approval window.

The corrected retained-dump restore passed again: 28 table counts, 11 critical
hashes, schema equivalence, role-grant and 12 exact sequence checks; the temporary
server is stopped. The corrected three-phase synthetic rollback passed. Negative
witness checks rejected missing table/hash evidence and a non-stopped source;
both scripts rejected optimized Python before starting work. Synthetic execution
of the exact CI comparison commands rejected changed and missing dashboard assets.
The version-consistency and metadata regression tests passed (2 tests).
These review results do not replace exact-candidate image CI or fresh cutover gates.

## Review disposition

No publication, migration, production stop/update, option change or provider request
is authorized by this document. Fresh stopped-writer backup/restore, installed-image
rollback assurance and post-update acceptance remain mandatory approval-window gates.
