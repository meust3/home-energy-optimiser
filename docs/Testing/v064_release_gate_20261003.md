# v0.6.4 solar forecast release gate - 3 October 2026

This preparation receipt records the initial gate state. Subsequent CI, Docker
recovery, backup/restore and controlled production update evidence is recorded in
[v0.6.4 production acceptance](v064_production_acceptance_20261003.md).
The pending statements below describe preparation time, not current deployment.

Scope: retain bounded Solcast half-hour forecast detail, add an explicit offline
morning-export diagnostic and replay. No schema change, reserve change, new
scheduler, executor, recommendation activation or retention activation.

This release is based on main at 79737ee and excludes the open optional AI
integration PR #7. Existing work in the AI checkout is preserved. Production was
independently observed running v0.6.3 with automatic updates disabled.

Isolated release source validation: 415 tests passed, 15 skipped; Ruff, Black and
whitespace checks passed. Skips include optional PostgreSQL/runtime cases and do
not establish container or production readiness. The earlier 486-test result was
from the checkout that also contained the optional AI candidate.

Docker Desktop was initially stopped. It was started, but the container gate is
not yet verified. Before publication/installation, validate the frozen source in
an amd64 image, image-baked App bootstrap, protected options, UID/GID, Ingress,
watchdog and SIGTERM. No hardware or production service was stopped or updated.

Before installation: independently verify live PostgreSQL revision 20260927_01,
HOLD-only/no-command and retention settings; obtain a fresh backup and validate
an isolated PostgreSQL 17 restore. Do not run a production migration. Keep the
previous App backup for rollback. After installation, verify fresh persisted
Solcast intervals, collection continuity, linked forecast/reserve/HOLD cycles,
Ingress and data health. The offline strategy remains unavailable in production
and stored historical snapshots are not backfilled.

Publication, exact-image validation, backup/restore and production acceptance
remain pending until separately evidenced. This file is a gate receipt, not
an acceptance claim.
