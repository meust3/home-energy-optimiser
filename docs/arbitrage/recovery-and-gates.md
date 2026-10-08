# Read-only Gate A and compatible recovery

This local candidate has not changed any live option, database or service.

## Publication/deployment separation

Local version 0.8.0 is an unused minor feature candidate; remote main and released
v0.7.0 resolve to c2f51838ad050e1ebfd3c843f1919206a89eb203. No tag was created.
Gate A approval must identify the exact local commit and private release-manifest
SHA. Publishing uses a reviewed branch/PR, exact-commit remote build and immutable
tag-resolved validation. The present local artifact is built by the actual
production Dockerfile with a SHA-checked git archive supplied as a BuildKit secret.
It is NOT a tag-resolved/remote-download attestation. Remote source download is
still the default path. Publication is not automatically App installation.

The reviewed workflow triggers only main PR/workflow_dispatch, installs isolated
CI dependencies, starts its own PostgreSQL, tests/builds/uploads validation artifacts.
It contains no production access, deployment, model credit or hardware step.
No workflow was invoked in this initial work package.

## Migration and containment

Startup requires manual schema head 20261008_01 even with capture disabled.
The additive migration creates arbitrage_input_captures and arbitrage_commit_witnesses,
including kind/time and ID indexes. It does not repair/reprocess old records.
Production migration is a Gate A action, not authorised by local preparation.

Before any approved installation: verify database identity/old head, current App
update setting, backup/output sizes and privileges; take an external full backup,
restore it into an exclusively owned PostgreSQL 17 instance and verify values;
preserve old image/options plus exact compatible replacement/recovery image.
Use only reviewed additive migration. Check one genuine new capture, post-commit
witness, normal core operation and disabled executor. Do not widen scope when a
snapshot/profile is missing. Explicit activation and any mapping/profile change
must be listed in the approval; default flags alone do not turn collection on.

Preferred containment retains schema-compatible candidate code with
arbitrage_capture_enabled=false and empty arbitrage_research_profile_json.
It preserves arbitrage history. Existing optional context collection may also be
disabled separately for a context-specific failure; retained context/weather rows
are not removed. Flags must be recorded in the approval, not changed now.
The exact compatible image identity is recorded in the private release manifest.

v0.7.0 rejects 20261008_01. Reinstalling it against the migrated database is not
compatible recovery. v0.6.5 rejects 20261005_01, as the maintained context runbook
already states. Physical downgrade 20261008_01 -> 20261005_01 deletes all arbitrage
captures/witnesses. Further downgrade deletes context/weather history as documented.
These are destructive, require separate explicit approval, and are not a rollback
instruction. No startup stamping, automatic migration/deletion or weakened schema
gate is added. Compatible containment does not solve an unrelated core failure.

## Resources and retention

No extra HA requests, no new polling thread, existing five-minute source snapshots
and thirty-minute forecast/advice only. Each source/decision/opportunity body is
bounded to 2 MiB and each series to 4,096 intervals. Each snapshot uses two short
transactions; optional connections use 1s connect and 500ms statement timeout.
Capture errors are class-only logs, no retry, and cannot invalidate a completed
core observation/forecast. Full-file snapshots contain exact bounds/provenance.
Maximum theoretical daily payload: 288 source + 48 decision + 48 opportunity
bodies = 768 MiB/day before database/index/JSON overhead (conservative limit,
not a measured usage prediction). Measured authored 24h sizes/runtime are in the
private receipt; installed throughput/storage must be checked at Gate A.
Retention does not prune these causal records and remains disabled. Set no new
retention policy without explicit future version and preservation review.

## Physical gates remain locked

Gate B must name exact action families, equipment/firmware, transport semantics,
power/energy/duration/cost/throughput/reserve caps, binding import/export limits,
feedback freshness, external-controller handover, finite device expiry or human
fallback, manual override and verified neutral end state. Charging approval never
permits export. Cloud registration, firmware and commissioning changes are separate.
A proposed acceptance plan is at least three successful supervised cycles per
approved family, including bounded normal completion, expiry and manual override,
plus one fake lost-ACK/restart/recovery rehearsal. This is a programme proposal,
not a certified threshold or automatic graduation. Real budgets remain unapproved.
Gate C requires separate capped policy authority and prospective economic/risk review.
